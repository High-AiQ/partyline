"""The write fence: wrap plan, git mirror, refusal, and the grant API.

The wrap is the kernel-level boundary under every text brief, so these
tests hold it to the strongest standard available: the argv plan is
asserted symbol by symbol, the git mirror is driven against a real
repository, and — where bubblewrap exists — a real fenced process is run
against a fixture repository to prove that an ordinary commit works while
the parent checkout, repo config, hooks, sibling branch refs, and sibling
worktree metadata stay byte-for-byte unchanged on the host.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, fence, git_fence, server
from partyline.auth_guard import install_auth_guard
from partyline.write_set_routes import list_write_grants, write_set_router
from partyline.db import Db
from partyline.features import overridden
from partyline.hierarchy_routes import hierarchy_router
from partyline.runtime import ChatRuntime

BWRAP_PRESENT = fence.bwrap_available()


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=f@example.com", "-c", "user.name=fence", *args, cwd=cwd)


def _worktree_fixture(base: str) -> dict:
    """A repository with the main branch, one sibling worktree, and the line's."""
    repo = os.path.join(base, "repo")
    os.makedirs(repo)
    _git("init", "-q", "-b", "main", cwd=repo)
    _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=repo)
    line_wt = os.path.join(base, "wt-line")
    sibling_wt = os.path.join(base, "wt-sibling")
    _git("worktree", "add", "-q", "-b", "line/demo", line_wt, cwd=repo)
    _git("worktree", "add", "-q", "-b", "line/sibling", sibling_wt, cwd=repo)
    return {"repo": repo, "line_wt": line_wt, "sibling_wt": sibling_wt}


def _att(cwd, conv_id="conv-fence", metadata=None, grants=None):
    return {"cwd": cwd, "conv_id": conv_id,
            "adapter_metadata": metadata or {}, "write_grants": grants or []}


class FakeAdapter:
    """Just the two surfaces the fence touches: att and build_command."""

    def __init__(self, att, command):
        self.att = att
        self._command = command

    def build_command(self):
        return list(self._command)


class LaunchArgvTest(unittest.TestCase):
    def test_flag_off_spawns_the_bare_command(self):
        adapter = FakeAdapter(_att("/tmp"), ["codex", "--flag"])
        with overridden(write_fence=False):
            self.assertEqual(fence.launch_argv(adapter), ["codex", "--flag"])

    def test_wrap_prefix_and_command_tail(self):
        argv = fence.launch_argv(FakeAdapter(_att("/tmp"), ["cli", "--go"]))
        self.assertEqual(argv[0], fence.BWRAP)
        self.assertIn("--die-with-parent", argv)
        self.assertEqual(argv[-3:], ["--", "cli", "--go"])
        for flag in ("--ro-bind", "--dev", "--proc", "--tmpfs"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--ro-bind") + 2], "/")

    def test_cwd_and_homes_are_writable_binds(self):
        argv = fence.launch_argv(FakeAdapter(_att("/tmp"), ["cli"]))
        pairs = [(argv[i + 1], argv[i + 2]) for i, a in enumerate(argv) if a == "--bind"]
        guests = {dst for _src, dst in pairs}
        self.assertIn("/tmp", guests)
        self.assertIn(os.path.expanduser("~/.cache"), guests)
        self.assertIn(os.path.expanduser("~/.config"), guests)

    def test_manifest_fence_args_apply_only_when_fenced(self):
        att = _att("/tmp", metadata={"fence_args": ["--yolo"], "write_paths": []})
        argv = fence.launch_argv(FakeAdapter(att, ["codex"]))
        self.assertEqual(argv[-2:], ["codex", "--yolo"])
        with overridden(write_fence=False):
            self.assertEqual(fence.launch_argv(FakeAdapter(att, ["codex"])), ["codex"])

    def test_missing_bwrap_refuses_rather_than_running_unconfined(self):
        with patch.object(fence, "BWRAP", "/nonexistent/bwrap"):
            with self.assertRaises(fence.FenceUnavailable):
                fence.launch_argv(FakeAdapter(_att("/tmp"), ["cli"]))

    def test_write_set_dedupes_and_skips_missing(self):
        with tempfile.TemporaryDirectory() as base:
            outside = os.path.join(base, "extra")
            os.makedirs(outside)
            att = _att(base, grants=[{"path": base},  # inside cwd: covered
                                     {"path": outside},
                                     {"path": os.path.join(base, "missing")}])
            with patch.object(git_fence, "FENCE_ROOT", os.path.join(base, "fence")):
                pairs = fence.write_set(att, adapter_paths=[])
            sources = [src for src, _dst, _ro in pairs]
            self.assertEqual(sources.count(base), 1)
            self.assertIn(outside, sources)
            self.assertNotIn(os.path.join(base, "missing"), sources)

    def test_manifest_write_paths_expand_and_bind(self):
        att = _att("/tmp", metadata={"write_paths": ["~/.grok"]})
        pairs = fence.write_set(att, adapter_paths=None)
        grok = os.path.expanduser("~/.grok")
        self.assertIn((grok, grok, False), pairs)


class GitMirrorTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.fix = _worktree_fixture(self.directory.name)
        self.addCleanup(shutil.rmtree, self.mirror_root(), ignore_errors=True)

    def mirror_root(self):
        return os.path.join(self.directory.name, "fence-root")

    def gitdir(self, wt):
        return git_fence._worktree_gitdir(wt)

    def test_mirror_keeps_own_branch_and_refreshes_siblings(self):
        common = git_fence.common_gitdir(self.gitdir(self.fix["line_wt"]))
        own_wt = self.fix["line_wt"]
        _identity("commit", "-q", "--allow-empty", "-m", "on line", cwd=own_wt)
        with patch.object(git_fence, "FENCE_ROOT", self.mirror_root()):
            mirror = git_fence.refresh_mirror(common, self.gitdir(own_wt), "conv-1")
        own_ref = os.path.join(mirror, "refs/heads/line/demo")
        self.assertTrue(os.path.isfile(own_ref))
        # A sibling ref moved after the first launch is refreshed, the own
        # branch is kept.
        _identity("commit", "-q", "--allow-empty", "-m", "on main one", cwd=self.fix["repo"])
        _identity("commit", "-q", "--allow-empty", "-m", "on main two", cwd=self.fix["repo"])
        mirror_main = os.path.join(mirror, "refs/heads/main")
        before = open(mirror_main).read()
        moved = _git("rev-parse", "main~1", cwd=self.fix["repo"]).stdout.strip()
        self.assertNotEqual(moved, before.strip())
        _git("update-ref", "refs/heads/main", moved, cwd=self.fix["repo"])
        with patch.object(git_fence, "FENCE_ROOT", self.mirror_root()):
            git_fence.refresh_mirror(common, self.gitdir(own_wt), "conv-1")
        self.assertNotEqual(open(mirror_main).read(), before)
        self.assertEqual(open(mirror_main).read(),
                         open(os.path.join(common, "refs/heads/main")).read())
        _git("update-ref", "refs/heads/main", before.strip(), cwd=self.fix["repo"])

    def test_refresh_replaces_symlinked_mirror_ref_without_touching_target(self):
        common = git_fence.common_gitdir(self.gitdir(self.fix["line_wt"]))
        target = os.path.join(self.directory.name, "host-target")
        with open(target, "w", encoding="utf-8") as file:
            file.write("host data must survive\n")
        with patch.object(git_fence, "FENCE_ROOT", self.mirror_root()):
            mirror = git_fence.refresh_mirror(common, self.gitdir(self.fix["line_wt"]),
                                              "conv-symlink")
            mirror_main = os.path.join(mirror, "refs/heads/main")
            os.unlink(mirror_main)
            os.symlink(target, mirror_main)
            git_fence.refresh_mirror(common, self.gitdir(self.fix["line_wt"]),
                                     "conv-symlink")

        with open(target, encoding="utf-8") as file:
            self.assertEqual(file.read(), "host data must survive\n")
        self.assertFalse(os.path.islink(mirror_main))
        self.assertTrue(os.path.isfile(mirror_main))
        with open(mirror_main, encoding="utf-8") as mirror_file:
            with open(os.path.join(common, "refs/heads/main"),
                      encoding="utf-8") as real_file:
                self.assertEqual(mirror_file.read(), real_file.read())

    def test_bind_plan_never_writes_real_refs_config_hooks(self):
        common = git_fence.common_gitdir(self.gitdir(self.fix["line_wt"]))
        with patch.object(git_fence, "FENCE_ROOT", self.mirror_root()):
            binds = git_fence.git_binds(self.fix["line_wt"], "conv-1")
        guests = {dst for _src, dst, _ro in binds}
        self.assertIn(os.path.join(common, "objects"), guests)          # shared, safe
        self.assertIn(os.path.join(common, "refs"), guests)             # the mirror
        self.assertIn(self.gitdir(self.fix["line_wt"]), guests)         # own metadata
        for forbidden in ("config", "hooks", "description", "HEAD"):
            self.assertNotIn(os.path.join(common, forbidden), guests)
        sources = {src for src, _dst, _ro in binds}
        worktrees_entry = [b for b in binds if b[1] == os.path.join(common, "worktrees")]
        self.assertEqual(worktrees_entry, [(os.path.join(common, "worktrees"),) * 2 + (True,)])
        for real in (os.path.join(common, "refs"), os.path.join(common, "config"),
                     os.path.join(common, "hooks"), os.path.join(common, "logs"),
                     os.path.join(common, "packed-refs")):
            self.assertNotIn(real, sources)

    def test_non_worktree_cwd_needs_no_git_binds(self):
        self.assertEqual(git_fence.git_binds(self.fix["repo"], "conv-1"), [])
        self.assertEqual(git_fence.git_binds(self.directory.name, "conv-1"), [])

    def test_worktree_link_garbage_is_not_a_worktree(self):
        base = self.directory.name
        for content in ("", "not a gitdir", f"gitdir: {base}/missing/worktrees/x",
                        f"gitdir: {base}/repo/.git/objects"):
            fake = os.path.join(base, "fake-wt")
            os.makedirs(fake, exist_ok=True)
            with open(os.path.join(fake, ".git"), "w") as file:
                file.write(content + "\n")
            self.assertIsNone(git_fence._worktree_gitdir(fake),
                              f"accepted: {content!r}")

    def test_packed_refs_are_mirrored_with_own_branch_loose(self):
        common = git_fence.common_gitdir(self.gitdir(self.fix["line_wt"]))
        _git("pack-refs", "--all", cwd=self.fix["repo"])
        self.assertIsNone(os.path.exists(os.path.join(
            common, "refs/heads/line/demo")) or None)
        with patch.object(git_fence, "FENCE_ROOT", self.mirror_root()):
            mirror = git_fence.refresh_mirror(common, self.gitdir(self.fix["line_wt"]),
                                              "conv-packed")
            binds = git_fence.git_binds(self.fix["line_wt"], "conv-packed")
        # The own branch lived only in packed-refs; the mirror materialises it
        # loose so the filtered packed copy cannot leave it unresolvable.
        packed_own = [line for line in open(os.path.join(mirror, "packed-refs"))
                      if line.endswith(" refs/heads/line/demo\n")]
        self.assertEqual(packed_own, [])
        loose = os.path.join(mirror, "refs/heads/line/demo")
        self.assertTrue(os.path.isfile(loose))
        self.assertEqual(open(loose).read().strip(),
                         git_fence._read_ref(common, "refs/heads/line/demo"))
        self.assertIn((os.path.join(mirror, "packed-refs"),
                       os.path.join(common, "packed-refs"), False), binds)

    def test_read_ref_returns_none_without_any_ref_source(self):
        self.assertIsNone(git_fence._read_ref(
            os.path.join(self.directory.name, "nope"), "refs/heads/x"))


@unittest.skipIf(not BWRAP_PRESENT, "bubblewrap is not installed")
class FenceIntegrationTest(unittest.TestCase):
    """A real fenced process against a real repository.

    Every negative here is host-side: after the fenced process ran, the
    protected path on the host must be byte-for-byte what it was.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.fix = _worktree_fixture(self.directory.name)
        self.addCleanup(shutil.rmtree, os.path.expanduser(
            os.path.join(git_fence.FENCE_ROOT, "conv-int")), ignore_errors=True)
        patcher = patch.object(git_fence, "FENCE_ROOT", self.mirror_root())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(_git, "worktree", "prune", cwd=self.fix["repo"])
        self.att = _att(self.fix["line_wt"], conv_id="conv-int")

    def mirror_root(self):
        return os.path.join(self.directory.name, "fence-root")

    def run_fenced(self, *args):
        argv = fence.launch_argv(FakeAdapter(self.att, list(args)), tmpfs_tmp=False)
        return subprocess.run(argv, capture_output=True, text=True, cwd=self.fix["line_wt"])

    def host_bytes(self, path):
        with open(path, "rb") as file:
            return file.read()

    def test_commit_works_and_protected_paths_are_untouched(self):
        common = git_fence.common_gitdir(git_fence._worktree_gitdir(self.fix["line_wt"]))
        real_main = os.path.join(common, "refs/heads/main")
        real_config = os.path.join(common, "config")
        real_hook = os.path.join(common, "hooks", "pre-commit")
        sibling_head = os.path.join(common, "worktrees", "wt-sibling", "HEAD")
        parent_file = os.path.join(self.fix["repo"], "tracked.txt")
        with open(parent_file, "w") as file:
            file.write("original\n")
        _git("add", "tracked.txt", cwd=self.fix["repo"])
        _identity("commit", "-q", "-m", "track", cwd=self.fix["repo"])
        before = {path: self.host_bytes(path) for path in
                  (real_main, real_config, sibling_head, parent_file)}

        self.assertEqual(self.run_fenced(
            "git", "-C", self.fix["line_wt"], "status", "--short").returncode, 0)
        marker = os.path.join(self.fix["line_wt"], "in-fence.txt")
        result = self.run_fenced("touch", marker)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(marker))
        self.run_fenced("git", "-C", self.fix["line_wt"], "add", "in-fence.txt")
        result = self.run_fenced("git", "-C", self.fix["line_wt"], "-c",
                                 "user.email=f@example.com", "-c", "user.name=fence",
                                 "commit", "-qm", "fenced work")
        self.assertEqual(result.returncode, 0, result.stderr)

        # The commit is readable from the real repository (an accept
        # fast-forward depends on it), but the real ref was never moved:
        # the line's branch advances in the mirror only.
        sha = _git("rev-parse", "HEAD", cwd=self.fix["line_wt"]).stdout.strip()
        kind = _git("cat-file", "-t", sha, cwd=self.fix["repo"]).stdout.strip()
        self.assertEqual(kind, "commit")
        self.assertNotEqual(self.host_bytes(real_main), sha.encode() + b"\n")

        # Negatives. Writes to the shared mirror (refs) may succeed — they
        # diverge from the real repository by design — while writes to
        # anything truly shared must fail; and in every case the host bytes
        # are unchanged.
        divergent = self.run_fenced(
            "git", "-C", self.fix["line_wt"], "update-ref", "refs/heads/main", sha)
        self.assertEqual(divergent.returncode, 0, divergent.stderr)
        for args in (
            ["touch", real_hook],
            ["touch", os.path.join(common, "hooks", "evil-hook")],
            ["sh", "-c", f"echo evil >> {real_config}"],
            ["touch", os.path.join(common, "worktrees", "wt-sibling", "evil")],
            ["sh", "-c", f"echo evil > {parent_file}"],
            ["touch", "/home/nonexistent-fence-probe"],
        ):
            result = self.run_fenced(*args)
            self.assertNotEqual(
                result.returncode, 0, f"write unexpectedly succeeded: {args}")
        for path, original in before.items():
            self.assertEqual(self.host_bytes(path), original, path)
        self.assertFalse(os.path.exists(os.path.join(common, "hooks", "evil-hook")))


class WriteSetGrantApiTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = os.path.join(self.directory.name, "repo")
        os.makedirs(self.repo)
        _git("init", "-q", "-b", "main", cwd=self.repo)
        _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=self.repo)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        app.include_router(write_set_router(self.runtime))

        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(setattr, server, "runtime", server.runtime)
        server.runtime = self.runtime
        self.db.create_conversation("root", "Root")
        self.db.add_attachment("root-lead", "root", "terra", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='root-lead'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.client.headers.update({"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])})
        made = self.client.post("/api/conversations/root/children", json={"name": "kid"})
        self.assertEqual(made.status_code, 201, made.text)
        self.kid = made.json()["conversation"]

    def machine(self, att_id):
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, att_id)}

    def test_person_grants_scope_and_it_is_recorded(self):
        target = os.path.join(self.directory.name, "shared-assets")
        response = self.client.post(f"/api/conversations/{self.kid['id']}/write-set",
                                    json={"path": target})
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()
        self.assertEqual([row["path"] for row in rows], [target])
        self.assertEqual(rows[0]["granted_by"], "person")

    def test_grant_is_idempotent(self):
        target = os.path.join(self.directory.name, "assets")
        for _ in range(2):
            response = self.client.post(f"/api/conversations/{self.kid['id']}/write-set",
                                        json={"path": target})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(list_write_grants(self.db, self.kid["id"])), 1)

    def test_the_line_itself_cannot_grant_its_own_scope(self):
        self.db.add_attachment("kid-worker", self.kid["id"], "worker", "fake",
                               ["fake"], self.directory.name)
        response = self.client.post(
            f"/api/conversations/{self.kid['id']}/write-set",
            json={"path": os.path.join(self.directory.name, "x")},
            headers=self.machine("kid-worker"))
        self.assertEqual(response.status_code, 403, response.text)

    def test_a_captain_above_can_grant(self):
        response = self.client.post(
            f"/api/conversations/{self.kid['id']}/write-set",
            json={"path": os.path.join(self.directory.name, "captain-granted")},
            headers=self.machine("root-lead"))
        self.assertEqual(response.status_code, 200, response.text)

    def test_an_unrelated_machine_cannot_grant(self):
        self.db.create_conversation("stranger", "Stranger")
        self.db.add_attachment("stranger-lead", "stranger", "other", "fake",
                               ["fake"], self.directory.name)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='stranger-lead'")
        response = self.client.post(
            f"/api/conversations/{self.kid['id']}/write-set",
            json={"path": os.path.join(self.directory.name, "y")},
            headers=self.machine("stranger-lead"))
        self.assertEqual(response.status_code, 403, response.text)

    def test_relative_and_root_paths_are_refused(self):
        for path in ("relative/path", "/", "/../escape", "/double//slash"):
            response = self.client.post(
                f"/api/conversations/{self.kid['id']}/write-set", json={"path": path})
            self.assertEqual(response.status_code, 400, f"{path}: {response.text}")

    def test_grant_on_a_missing_line_is_404(self):
        response = self.client.post("/api/conversations/ghost/write-set",
                                    json={"path": "/tmp/x"})
        self.assertEqual(response.status_code, 404, response.text)

    def test_listing_requires_read_scope(self):
        listing = self.client.get(f"/api/conversations/{self.kid['id']}/write-set")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json(), [])

    def test_a_granted_path_reaches_the_spawn_write_set(self):
        target = os.path.join(self.directory.name, "granted-dir")
        os.makedirs(target)
        self.client.post(f"/api/conversations/{self.kid['id']}/write-set",
                         json={"path": target})
        att = _att(self.repo, conv_id=self.kid["id"],
                   grants=list_write_grants(self.db, self.kid["id"]))
        with patch.object(git_fence, "FENCE_ROOT",
                          os.path.join(self.directory.name, "fence-root")):
            pairs = fence.write_set(att, adapter_paths=[])
        self.assertIn((target, target, False), pairs)


if __name__ == "__main__":
    unittest.main()
