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
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import (auth_store, auth_tokens, fence, fence_darwin, fence_paths, fence_probe,
                       fence_protect,
                       git_fence, server)
from partyline.auth_guard import install_auth_guard
from partyline.write_set_routes import list_write_grants, write_set_router
from partyline.write_set_requests import register_write_set_request_routes
from partyline.db import Db
from partyline.features import overridden
from partyline.hierarchy_routes import hierarchy_router
from partyline.runtime import ChatRuntime
from partyline.review_worktrees import create_review_worktree, list_review_worktrees

def _bwrap_skip_reason():
    if not fence.bwrap_available():
        return "bubblewrap is not installed"
    try:
        result = subprocess.run(
            [fence.BWRAP, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
             "--", "true"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"bubblewrap cannot create a user namespace: {exc}"
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "namespace probe failed"
        return f"bubblewrap cannot create a user namespace: {detail}"
    return None


BWRAP_SKIP_REASON = _bwrap_skip_reason()


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=f@example.com", "-c", "user.name=fence", *args, cwd=cwd)


def _worktree_fixture(base: str) -> dict:
    """A repository with the main branch, one sibling worktree, and the line's."""
    repo = os.path.join(base, "repo")
    os.makedirs(repo)
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "f@example.com", cwd=repo)
    _git("config", "user.name", "fence", cwd=repo)
    _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=repo)
    line_wt = os.path.join(base, "wt-line")
    sibling_wt = os.path.join(base, "wt-sibling")
    _git("worktree", "add", "-q", "-b", "line/demo", line_wt, cwd=repo)
    _git("worktree", "add", "-q", "-b", "line/sibling", sibling_wt, cwd=repo)
    return {"repo": repo, "line_wt": line_wt, "sibling_wt": sibling_wt}


def _att(cwd, conv_id="conv-fence", metadata=None, grants=None):
    return {"cwd": cwd, "conv_id": conv_id,
            "adapter_metadata": metadata or {}, "write_grants": grants or [],
            "protected_roots": [], "db_paths": []}


def _isolate_home(test_case, root=None):
    if root is None:
        test_case.home = tempfile.TemporaryDirectory()
        test_case.addCleanup(test_case.home.cleanup)
        root = test_case.home.name
    os.makedirs(root, exist_ok=True)
    home_patch = patch.dict(os.environ, {"HOME": root})
    home_patch.start()
    test_case.addCleanup(home_patch.stop)
    for name in (".cache", ".config", ".grok"):
        os.makedirs(os.path.join(root, name), exist_ok=True)


class FakeAdapter:
    """Just the two surfaces the fence touches: att and build_command."""

    def __init__(self, att, command):
        self.att = att
        self._command = command

    def build_command(self):
        return list(self._command)


class LaunchArgvTest(unittest.TestCase):
    def setUp(self):
        _isolate_home(self)

    def test_flag_off_spawns_the_bare_command(self):
        adapter = FakeAdapter(_att("/tmp"), ["codex", "--flag"])
        with overridden(write_fence=False):
            self.assertEqual(fence.launch_argv(adapter), ["codex", "--flag"])

    def test_wrap_prefix_and_command_tail(self):
        with tempfile.TemporaryDirectory() as base:
            att = _att(base)
            att["protected_roots"] = [base]
            with patch.object(fence, "bwrap_available", return_value=True):
                argv = fence.launch_argv(FakeAdapter(att, ["cli", "--go"]))
        self.assertEqual(argv[0], fence.BWRAP)
        self.assertIn("--die-with-parent", argv)
        self.assertEqual(argv[-3:], ["--", "cli", "--go"])
        for flag in ("--bind", "--ro-bind", "--dev-bind", "--proc"):
            self.assertIn(flag, argv)
        self.assertNotIn("--tmpfs", argv)
        self.assertEqual(argv[argv.index("--bind") + 1:argv.index("--bind") + 3], ["/", "/"])
        self.assertEqual(argv[argv.index("--ro-bind") + 1:argv.index("--ro-bind") + 3],
                         [base, base])

    def test_cwd_is_a_writable_bind(self):
        with patch.object(fence, "bwrap_available", return_value=True):
            argv = fence.launch_argv(FakeAdapter(_att("/tmp"), ["cli"]))
        pairs = [(argv[i + 1], argv[i + 2]) for i, a in enumerate(argv) if a == "--bind"]
        guests = {dst for _src, dst in pairs}
        self.assertIn("/tmp", guests)
        self.assertNotIn(os.path.expanduser("~/.cache"), guests)

    def test_protected_repository_and_database_are_read_only_before_carveouts(self):
        with tempfile.TemporaryDirectory() as base:
            repo = os.path.join(base, "repo")
            line = os.path.join(repo, "worktree")
            os.makedirs(line)
            database = os.path.join(base, "partyline.db")
            open(database, "w").close()
            att = _att(line)
            att.update(protected_roots=[repo], db_paths=[database])
            with patch.object(fence, "bwrap_available", return_value=True):
                argv = fence.launch_argv(FakeAdapter(att, ["cli"]))
            repo_ro = argv.index("--ro-bind")
            own_rw = argv.index("--bind", repo_ro)
            db_ro = argv.index("--ro-bind", own_rw)
            self.assertEqual(argv[repo_ro + 1:repo_ro + 3], [repo, repo])
            self.assertEqual(argv[own_rw + 1:own_rw + 3], [line, line])
            self.assertEqual(argv[db_ro + 1:db_ro + 3], [database, database])
            self.assertLess(repo_ro, own_rw)
            self.assertLess(own_rw, db_ro)

    def test_a_write_grant_is_bound_after_protected_roots(self):
        with tempfile.TemporaryDirectory() as base:
            repo = os.path.join(base, "repo")
            line = os.path.join(repo, "worktree")
            grant = os.path.join(repo, "shared")
            os.makedirs(line)
            os.makedirs(grant)
            att = _att(line, grants=[{"path": grant}])
            att["protected_roots"] = [repo]
            with patch.object(fence, "bwrap_available", return_value=True):
                argv = fence.launch_argv(FakeAdapter(att, ["cli"]))
            ro = argv.index("--ro-bind")
            rw = argv.index("--bind", ro)
            self.assertEqual(argv[ro + 1:ro + 3], [repo, repo])
            self.assertEqual(argv[rw + 1:rw + 3], [line, line])
            last = max(i for i, item in enumerate(argv) if item == "--bind")
            self.assertEqual(argv[last + 1:last + 3], [grant, grant])

    def test_manifest_fence_args_apply_only_when_fenced(self):
        att = _att("/tmp", metadata={"fence_args": ["--yolo"]})
        with patch.object(fence, "bwrap_available", return_value=True):
            argv = fence.launch_argv(FakeAdapter(att, ["codex"]))
        self.assertEqual(argv[-2:], ["codex", "--yolo"])
        with overridden(write_fence=False):
            self.assertEqual(fence.launch_argv(FakeAdapter(att, ["codex"])), ["codex"])

    def test_fence_args_dedupe_against_the_command(self):
        flag = "--dangerously-bypass-approvals-and-sandbox"
        att = _att("/tmp", metadata={"fence_args": [flag]})
        with patch.object(fence, "bwrap_available", return_value=True):
            carrying = fence.launch_argv(FakeAdapter(att, ["codex", flag, "--go"]))
            self.assertEqual(carrying[-3:], ["codex", flag, "--go"])
            self.assertEqual(carrying.count(flag), 1)
            bare = fence.launch_argv(FakeAdapter(att, ["codex"]))
            self.assertEqual(bare[-2:], ["codex", flag])
            self.assertEqual(bare.count(flag), 1)

    def test_missing_bwrap_refuses_rather_than_running_unconfined(self):
        with patch.object(fence, "BWRAP", "/nonexistent/bwrap"):
            with self.assertRaises(fence.FenceUnavailable):
                fence.launch_argv(FakeAdapter(_att("/tmp"), ["cli"]))

    def test_memory_preflight_still_blocks_launch_when_filesystem_fence_is_disabled(self):
        result = (False, "service memory guard missing", "install the unit drop-in")
        with overridden(write_fence=False), patch.object(
            fence_probe, "cached_result", return_value=result
        ):
            with self.assertRaisesRegex(fence.FenceUnavailable, "install the unit drop-in"):
                fence.launch_argv(FakeAdapter(_att("/tmp"), ["cli"]))

    def test_failed_boot_probe_refuses_with_the_banner_remedy(self):
        result = (False, "user namespace unavailable", "apt-get install -y bubblewrap")
        with patch.object(fence, "backend_available", return_value=(True, "")), \
                patch.object(fence_probe, "cached_result", return_value=result):
            with self.assertRaisesRegex(fence.FenceUnavailable, "apt-get install -y bubblewrap"):
                fence.launch_argv(FakeAdapter(_att("/tmp"), ["cli"]))

    def test_missing_backend_refuses_with_cached_boot_failure(self):
        reason = "bubblewrap is missing; Ubuntu AppArmor profile unavailable"
        remedy = "apt-get install -y bubblewrap"
        result = (False, reason, remedy)
        with patch.object(fence_probe, "cached_result", return_value=result), \
                patch.object(fence, "backend_available", return_value=(False, "bubblewrap is missing")):
            with self.assertRaises(fence.FenceUnavailable) as caught:
                fence.launch_argv(FakeAdapter(_att("/tmp"), ["cli"]))
        self.assertIn(reason, str(caught.exception))
        self.assertIn(remedy, str(caught.exception))

    def test_write_set_dedupes_and_skips_missing(self):
        with tempfile.TemporaryDirectory() as base:
            att = _att(base)
            with patch.object(git_fence, "FENCE_ROOT", os.path.join(base, "fence")):
                pairs = fence.write_set(att)
            sources = [src for src, _dst, _ro in pairs]
            self.assertEqual(sources.count(base), 1)
            self.assertNotIn(os.path.join(base, "missing"), sources)


class DarwinSandboxExecTest(unittest.TestCase):
    """The Darwin seam: backend choice, profile plan, and fail-closed
    refusal, asserted with sys.platform patched — no sandbox-exec binary
    is needed on Linux, and none of this runs a real sandbox.
    """

    def setUp(self):
        _isolate_home(self)

    def darwin(self):
        return patch.object(sys, "platform", "darwin")

    def test_backend_is_chosen_by_platform(self):
        with patch.object(sys, "platform", "linux"):
            self.assertEqual(fence.backend(), "bubblewrap")
        with self.darwin():
            self.assertEqual(fence.backend(), "sandbox-exec")
        with patch.object(sys, "platform", "win32"):
            self.assertEqual(fence.backend(), "none")

    def test_darwin_argv_is_profile_then_command(self):
        with self.darwin(), \
                patch.object(fence_darwin, "sandbox_exec_available", return_value=True):
            argv = fence.launch_argv(FakeAdapter(_att("/tmp"), ["cli", "--go"]))
        self.assertEqual(argv[0], fence_darwin.SANDBOX_EXEC)
        self.assertEqual(argv[1], "-p")
        self.assertTrue(argv[2].startswith("(version 1)\n(allow default)\n(allow file-write*"))
        self.assertEqual(argv[3:], ["cli", "--go"])

    def test_darwin_codex_home_allowed_only_when_it_exists(self):
        with tempfile.TemporaryDirectory() as base:
            repo = os.path.join(base, "repo")
            line = os.path.join(repo, "worktree")
            os.makedirs(line)
            database = os.path.join(base, "db")
            open(database, "w").close()
            att = _att(line)
            att.update(protected_roots=[repo], db_paths=[database])
            with self.darwin(), \
                    patch.object(fence_darwin, "sandbox_exec_available", return_value=True):
                argv = fence.launch_argv(FakeAdapter(att, ["codex"]))
            profile = argv[2]
            deny = profile.index("(deny file-write*")
            allow = profile.index("(allow file-write*")
            self.assertLess(deny, allow)
            self.assertIn(f'(subpath "{repo}")', profile[:allow])
            self.assertIn(f'(subpath "{database}")', profile[:allow])
            self.assertIn(f'(subpath "{line}")', profile[allow:])

    def test_darwin_fence_args_apply_and_dedupe(self):
        flag = "--dangerously-bypass-approvals-and-sandbox"
        att = _att("/tmp", metadata={"fence_args": [flag]})
        with self.darwin(), \
                patch.object(fence_darwin, "sandbox_exec_available", return_value=True):
            bare = fence.launch_argv(FakeAdapter(att, ["codex"]))
            carrying = fence.launch_argv(FakeAdapter(att, ["codex", flag]))
        self.assertEqual(bare[3:], ["codex", flag])
        self.assertEqual(carrying[3:], ["codex", flag])
        for argv in (bare, carrying):
            self.assertEqual(argv.count(flag), 1)

    def test_linux_plan_stays_the_bwrap_argv(self):
        with patch.object(sys, "platform", "linux"), \
                patch.object(fence, "bwrap_available", return_value=True):
            self.assertEqual(fence.backend_available(), (True, ""))
            argv = fence.launch_argv(FakeAdapter(_att("/tmp"), ["cli", "--go"]))
        self.assertEqual(argv[0], fence.BWRAP)
        self.assertEqual(argv[-3:], ["--", "cli", "--go"])
        self.assertIn("--unshare-user", argv)

    def test_profile_denies_protected_paths_then_reallows_carveouts(self):
        text = fence_darwin.profile(["/some/repo"], ["/some/repo/.partyline-worktrees/line"])
        self.assertEqual(text.splitlines()[:2], ["(version 1)", "(allow default)"])
        self.assertTrue(text.splitlines()[2].startswith("(deny file-write*"))
        self.assertIn('(subpath "/some/repo")', text)
        self.assertIn('(subpath "/some/repo/.partyline-worktrees/line")', text)
        self.assertIn('(subpath "/private/tmp")', text)
        self.assertIn('(literal "/dev/null")', text)
        self.assertIn('(regex #"^/dev/ttys[0-9]+$")', text)
        for outside in ("/", "/etc", "/Users", "/private/etc", "/usr", "/var",
                        "/some", "/some/repo-elsewhere"):
            self.assertNotIn(f'(subpath "{outside}")', text)
            self.assertNotIn(f'(literal "{outside}")', text)

    def test_profile_names_the_process_temp_dir_in_both_spellings(self):
        with tempfile.TemporaryDirectory() as base:
            tmpdir = os.path.join(base, "T")
            os.makedirs(tmpdir)
            with patch.dict(os.environ, {"TMPDIR": tmpdir}):
                text = fence_darwin.profile([], [])
        self.assertIn(f'(subpath "{tmpdir}")', text)
        self.assertIn(f'(subpath "{os.path.realpath(tmpdir)}")', text)
        self.assertIn('(subpath "/private/tmp")', text)

    def test_profile_escapes_quotes_and_backslashes(self):
        weird = '/tmp/space dir and "quote" and back\\slash'
        text = fence_darwin.profile([weird], [])
        self.assertIn('(subpath "/tmp/space dir and \\"quote\\" and back\\\\slash")', text)

    def test_darwin_write_set_is_the_weaker_documented_git_scope(self):
        with tempfile.TemporaryDirectory() as base:
            fix = _worktree_fixture(base)
            _git("pack-refs", "--all", cwd=fix["repo"])  # so packed-refs exists to grant
            sha = _git("rev-parse", "HEAD", cwd=fix["line_wt"]).stdout.strip()
            review_root = os.path.join(fix["repo"], ".review")
            os.makedirs(review_root)
            review = os.path.join(review_root, sha)
            _git("worktree", "add", "-q", "--detach", review, sha, cwd=fix["repo"])
            att = _att(fix["line_wt"], conv_id="owner")
            att["review_worktrees"] = [{"conv_id": "owner", "sha": sha, "path": review}]
            fence_root = os.path.join(base, "fence-root")
            with patch.object(git_fence, "FENCE_ROOT", fence_root):
                paths = fence.darwin_write_set(att)
            self.assertFalse(os.path.exists(fence_root))  # no mirror on Darwin
            gitdir = git_fence._worktree_gitdir(fix["line_wt"])
            common = git_fence.common_gitdir(gitdir)
            for path in (fix["line_wt"], gitdir, os.path.join(common, "objects"),
                         os.path.join(common, "refs"), os.path.join(common, "logs"),
                         os.path.join(common, "packed-refs"), review,
                         git_fence._worktree_gitdir(review)):
                self.assertIn(path, paths)
            for forbidden in ("config", "hooks", "description", "worktrees"):
                self.assertNotIn(os.path.join(common, forbidden), paths)
            self.assertEqual(git_fence.darwin_write_paths(fix["repo"]), [])

    def test_darwin_argv_allows_that_scope_and_nothing_wider(self):
        with tempfile.TemporaryDirectory() as base:
            fix = _worktree_fixture(base)
            att = _att(fix["line_wt"])
            with self.darwin(), \
                    patch.object(fence_darwin, "sandbox_exec_available", return_value=True):
                argv = fence.launch_argv(FakeAdapter(att, ["git", "status"]))
            text = argv[2]
            gitdir = git_fence._worktree_gitdir(fix["line_wt"])
            common = git_fence.common_gitdir(gitdir)
            self.assertIn(f'(subpath "{common}")', text)
            self.assertIn(f'(subpath "{gitdir}")', text)
            self.assertIn(f'(subpath "{os.path.join(common, "refs")}")', text)
            for name in ("config", "hooks", "worktrees", "description", "HEAD", "info", "branches"):
                path = os.path.join(common, name)
                if os.path.lexists(path):
                    self.assertIn(f'(subpath "{path}")', text)
            deny_git = text.rindex("(deny file-write*")
            allow_gitdir = text.rindex("(allow file-write*")
            self.assertGreater(text.index(f'(subpath "{os.path.join(common, "config")}")'), deny_git)
            self.assertLess(text.index(f'(subpath "{os.path.join(common, "config")}")'), allow_gitdir)
            self.assertGreater(text.rindex(f'(subpath "{gitdir}")'), deny_git)

    def test_darwin_without_sandbox_exec_fails_closed_with_install_remedy(self):
        with self.darwin(), \
                patch.object(fence_darwin, "sandbox_exec_available", return_value=False):
            self.assertEqual(fence.backend_available(), (
                False, f"{fence_darwin.SANDBOX_EXEC} is missing or not executable"))
            with self.assertRaises(fence.FenceUnavailable) as caught:
                fence.launch_argv(FakeAdapter(_att("/tmp"), ["cli"]))
        self.assertIn("sandbox-exec", str(caught.exception))
        self.assertIn("Remedy:", str(caught.exception))

    def test_a_platform_with_no_backend_fails_closed(self):
        with patch.object(sys, "platform", "win32"):
            available, reason = fence.backend_available()
            self.assertFalse(available)
            self.assertIn("win32", reason)
            with self.assertRaises(fence.FenceUnavailable):
                fence.launch_argv(FakeAdapter(_att("/tmp"), ["cli"]))

    def test_sandbox_exec_availability_checks_the_real_binary(self):
        with patch("os.path.isfile", return_value=True), \
                patch("os.access", return_value=True):
            self.assertTrue(fence_darwin.sandbox_exec_available())
        with patch("os.path.isfile", return_value=False):
            self.assertFalse(fence_darwin.sandbox_exec_available())


class ProtectListTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.fix = _worktree_fixture(self.directory.name)
        self.addCleanup(_git, "worktree", "prune", cwd=self.fix["repo"])
        self.db = Db(os.path.join(self.directory.name, "partyline.db"))
        self.addCleanup(self.db.close)

    def test_active_lines_protect_each_repo_once_and_archived_lines_drop_out(self):
        self.db.create_conversation("root", "root")
        self.db.create_conversation("child", "child")
        self.db.create_conversation("cwd-only", "cwd only")
        self.db.create_conversation("archived", "archived")
        self.db.add_attachment("root-att", "root", "root", "fake", ["fake"], self.fix["repo"])
        self.db.add_attachment("child-att", "child", "child", "fake", ["fake"],
                               self.fix["line_wt"])
        second = os.path.join(self.directory.name, "cwd-only-repo")
        os.makedirs(second)
        _git("init", "-q", cwd=second)
        self.db._exec("UPDATE conversations SET cwd=? WHERE id='cwd-only'", (second,))
        archived = os.path.join(self.directory.name, "archived-repo")
        os.makedirs(archived)
        _git("init", "-q", cwd=archived)
        self.db.add_attachment("archived-att", "archived", "archived", "fake", ["fake"], archived)
        self.db.archive_conversation("archived")
        self.assertEqual(fence_protect.protected_repo_roots(self.db),
                         sorted([self.fix["repo"], second]))

    def test_only_a_root_checkout_is_exempt_from_its_repository(self):
        self.assertEqual(fence_protect.own_repo_root(self.fix["repo"]), self.fix["repo"])
        self.assertIsNone(fence_protect.own_repo_root(self.fix["line_wt"]))

    def test_database_paths_include_runtime_lock_and_sqlite_sidecars(self):
        paths = [
            self.db.path, self.db.runtime_lock_path, self.db.path + "-wal",
            self.db.path + "-shm",
        ]
        self.assertFalse(os.path.exists(self.db.path + "-journal"))
        self.assertTrue(all(os.path.isfile(path) for path in paths))
        for path in paths[1:]:
            os.unlink(path)

        paths = fence_protect.database_paths(self.db)
        self.assertEqual(paths, [
            self.db.path, self.db.runtime_lock_path, self.db.path + "-wal",
            self.db.path + "-shm",
        ])
        self.assertTrue(all(os.path.isfile(path) for path in paths))

        att = _att(self.directory.name)
        att["db_paths"] = paths
        with patch.object(fence, "bwrap_available", return_value=True):
            argv = fence.launch_argv(FakeAdapter(att, ["cli"]))
        read_only_binds = {
            (argv[index + 1], argv[index + 2])
            for index, flag in enumerate(argv)
            if flag == "--ro-bind"
        }
        self.assertTrue(all((path, path) in read_only_binds for path in paths))
        self.db._exec("SELECT 1")  # SQLite tolerates the empty pre-created sidecars.


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

    def test_bind_plan_mirrors_git_root_and_protects_shared_paths(self):
        common = git_fence.common_gitdir(self.gitdir(self.fix["line_wt"]))
        with patch.object(git_fence, "FENCE_ROOT", self.mirror_root()):
            binds = git_fence.git_binds(self.fix["line_wt"], "conv-1")
        guests = {dst for _src, dst, _ro in binds}
        self.assertIn(os.path.join(common, "objects"), guests)          # shared, safe
        self.assertIn(os.path.join(common, "refs"), guests)             # the mirror
        self.assertIn(self.gitdir(self.fix["line_wt"]), guests)         # own metadata
        self.assertIn(common, guests)                                    # private root overlay
        for forbidden in ("description", "HEAD"):
            self.assertNotIn(os.path.join(common, forbidden), guests)
        sources = {src for src, _dst, _ro in binds}
        worktrees_entry = [b for b in binds if b[1] == os.path.join(common, "worktrees")]
        self.assertEqual(worktrees_entry, [(os.path.join(common, "worktrees"),) * 2 + (True,)])
        self.assertIn(os.path.join(common, "objects"), sources)
        self.assertIn(os.path.join(common, "config"), sources)
        self.assertIn(os.path.join(common, "hooks"), sources)
        self.assertNotIn(os.path.join(common, "refs"), sources)
        self.assertNotIn(os.path.join(common, "logs"), sources)
        self.assertNotIn(os.path.join(common, "packed-refs"), sources)

    def test_root_mirror_refreshes_real_root_files_without_config_or_hooks(self):
        common = git_fence.common_gitdir(self.gitdir(self.fix["line_wt"]))
        fetch_head = os.path.join(common, "FETCH_HEAD")
        info_exclude = os.path.join(common, "info", "exclude")
        with open(info_exclude, "a", encoding="utf-8") as file:
            file.write("private-overlay-probe\n")
        with open(fetch_head, "w", encoding="utf-8") as file:
            file.write("first\n")
        with patch.object(git_fence, "FENCE_ROOT", self.mirror_root()):
            mirror = git_fence._mirror_dir(common, "conv-root")
            git_fence.refresh_root_mirror(common, mirror)
            with open(fetch_head, "w", encoding="utf-8") as file:
                file.write("second\n")
            git_fence.refresh_root_mirror(common, mirror)
        with open(os.path.join(mirror, "FETCH_HEAD"), encoding="utf-8") as file:
            self.assertEqual(file.read(), "second\n")
        with open(os.path.join(mirror, "info", "exclude"), encoding="utf-8") as file:
            self.assertIn("private-overlay-probe", file.read())
        self.assertFalse(os.path.exists(os.path.join(mirror, "config")))
        self.assertFalse(os.path.exists(os.path.join(mirror, "hooks")))

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


class ReviewWorktreeFencePathTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.fix = _worktree_fixture(self.directory.name)
        self.addCleanup(_git, "worktree", "prune", cwd=self.fix["repo"])
        self.sha = _git("rev-parse", "HEAD", cwd=self.fix["line_wt"]).stdout.strip()
        review_root = os.path.join(self.fix["repo"], ".review")
        os.makedirs(review_root)
        self.path = os.path.join(review_root, self.sha)
        _git("worktree", "add", "-q", "--detach", self.path, self.sha, cwd=self.fix["repo"])

    def test_only_canonical_owned_rows_for_the_repository_are_accepted(self):
        row = {"conv_id": "owner", "sha": self.sha, "path": self.path}
        att = _att(self.fix["line_wt"], conv_id="owner")
        att["review_worktrees"] = [row]
        self.assertEqual(fence_paths._review_worktree_paths(att), [self.path])

        row["conv_id"] = "sibling"
        self.assertEqual(fence_paths._review_worktree_paths(att), [])
        row["conv_id"] = "owner"
        row["path"] = os.path.join(self.directory.name, "relocated")
        self.assertEqual(fence_paths._review_worktree_paths(att), [])

    def test_symlinked_review_path_is_not_granted(self):
        sha = "a" * 40
        path = os.path.join(self.fix["repo"], ".review", sha)
        os.symlink(self.fix["sibling_wt"], path)
        att = _att(self.fix["line_wt"], conv_id="owner")
        att["review_worktrees"] = [{"conv_id": "owner", "sha": sha, "path": path}]
        self.assertEqual(fence_paths._review_worktree_paths(att), [])

    def test_root_checkout_skips_the_mirror_over_its_own_git_dir(self):
        att = _att(self.fix["repo"], conv_id="owner")
        att["review_worktrees"] = [{"conv_id": "owner", "sha": self.sha, "path": self.path}]
        git_dir = os.path.join(self.fix["repo"], ".git")
        pairs = fence.write_set(att)
        for _src, dst, _ro in pairs:
            self.assertFalse(
                dst == git_dir or dst.startswith(git_dir + os.sep), dst)

    def test_linked_worktree_checkout_keeps_the_mirror_binds(self):
        att = _att(self.fix["line_wt"], conv_id="owner")
        att["review_worktrees"] = [{"conv_id": "owner", "sha": self.sha, "path": self.path}]
        common = git_fence.common_gitdir(git_fence._worktree_gitdir(self.fix["line_wt"]))
        with patch.object(git_fence, "FENCE_ROOT",
                          os.path.join(self.directory.name, "fence-root")):
            pairs = fence.write_set(att)
        dests = {dst for _src, dst, _ro in pairs}
        self.assertIn(os.path.join(common, "refs"), dests)


@unittest.skipUnless(BWRAP_SKIP_REASON is None, BWRAP_SKIP_REASON or "")
class FenceIntegrationTest(unittest.TestCase):
    """A real fenced process against a real repository.

    Every negative here is host-side: after the fenced process ran, the
    protected path on the host must be byte-for-byte what it was.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        _isolate_home(self, os.path.join(self.directory.name, "home"))
        self.fix = _worktree_fixture(self.directory.name)
        patcher = patch.object(git_fence, "FENCE_ROOT", self.mirror_root())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, os.path.join(self.mirror_root(), "conv-int"),
                        ignore_errors=True)
        self.addCleanup(_git, "worktree", "prune", cwd=self.fix["repo"])
        self.att = _att(self.fix["line_wt"], conv_id="conv-int")
        self.att["protected_roots"] = [self.fix["repo"]]

    def mirror_root(self):
        return os.path.join(self.directory.name, "fence-root")

    def run_fenced(self, *args):
        argv = fence.launch_argv(FakeAdapter(self.att, list(args)))
        return subprocess.run(argv, capture_output=True, text=True, cwd=self.fix["line_wt"])

    def host_bytes(self, path):
        with open(path, "rb") as file:
            return file.read()

    def common_root_files(self):
        common = git_fence.common_gitdir(git_fence._worktree_gitdir(self.fix["line_wt"]))
        return {
            name: self.host_bytes(os.path.join(common, name))
            for name in os.listdir(common)
            if os.path.isfile(os.path.join(common, name)) and
            not os.path.islink(os.path.join(common, name))
        }

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

    def test_recorded_review_worktree_gets_its_own_git_metadata_bind(self):
        db = Db(os.path.join(self.directory.name, "review-lines.db"))
        self.addCleanup(db.close)
        db.create_conversation("conv-int", "line")
        db.create_conversation("conv-sibling", "sibling")
        db.add_attachment("line-worker", "conv-int", "worker", "fake", ["fake"],
                          self.fix["line_wt"])
        db.add_attachment("sibling-worker", "conv-sibling", "worker", "fake", ["fake"],
                          self.fix["sibling_wt"])
        own_sha = _git("rev-parse", "HEAD", cwd=self.fix["line_wt"]).stdout.strip()
        _identity("commit", "-q", "--allow-empty", "-m", "sibling review",
                  cwd=self.fix["sibling_wt"])
        sibling_sha = _git("rev-parse", "HEAD", cwd=self.fix["sibling_wt"]).stdout.strip()
        own = create_review_worktree(db, "conv-int", own_sha)
        sibling = create_review_worktree(db, "conv-sibling", sibling_sha)
        self.att["review_worktrees"] = list_review_worktrees(db, "conv-int")

        with patch.object(git_fence, "FENCE_ROOT", self.mirror_root()):
            pairs = fence.write_set(self.att)
            own_gitdir = git_fence._worktree_gitdir(own["path"])
            sibling_gitdir = git_fence._worktree_gitdir(sibling["path"])
            review_root = os.path.join(self.fix["repo"], ".review")
            line_gitdir = git_fence._worktree_gitdir(self.fix["line_wt"])
            common = git_fence.common_gitdir(line_gitdir)
            self.assertIn((review_root, review_root, False), pairs)
            self.assertIn((own_gitdir, own_gitdir, False), pairs)
            self.assertIn((os.path.join(common, "worktrees"),
                           os.path.join(common, "worktrees"), True), pairs)
            self.assertNotIn((sibling_gitdir, sibling_gitdir, False), pairs)

            own_marker = os.path.join(own["path"], "review-write.txt")
            self.assertEqual(self.run_fenced("touch", own_marker).returncode, 0)
            result = self.run_fenced("git", "-C", own["path"], "add", "review-write.txt")
            self.assertEqual(result.returncode, 0, result.stderr)
            sibling_marker = os.path.join(sibling["path"], "shared-review-write.txt")
            result = self.run_fenced("touch", sibling_marker)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.isfile(sibling_marker))

    def test_new_review_checkout_is_writable_but_repo_and_sibling_are_not(self):
        self.att["protected_roots"].append(self.fix["sibling_wt"])
        review_root = os.path.join(self.fix["repo"], ".review")
        new_dir = os.path.join(review_root, "new-checkout")
        review_marker = os.path.join(new_dir, "gate-marker")
        root_marker = os.path.join(self.fix["repo"], "fence-root-probe")
        sibling_marker = os.path.join(self.fix["sibling_wt"], "fence-sibling-probe")
        self.assertFalse(os.path.exists(new_dir))
        script = " && ".join((
            f"mkdir -p {shlex.quote(new_dir)}",
            f"touch {shlex.quote(review_marker)}",
            f"! touch {shlex.quote(root_marker)} 2>/dev/null",
            f"! touch {shlex.quote(sibling_marker)} 2>/dev/null",
        ))
        result = self.run_fenced("sh", "-c", script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(review_marker))
        self.assertFalse(os.path.exists(root_marker))
        self.assertFalse(os.path.exists(sibling_marker))

    def test_git_root_transient_writes_stay_in_the_private_overlay(self):
        root_file = os.path.join(self.fix["repo"], "root.txt")
        with open(root_file, "w", encoding="utf-8") as file:
            file.write("base\n")
        _git("add", "root.txt", cwd=self.fix["repo"])
        _identity("commit", "-q", "-m", "base", cwd=self.fix["repo"])
        _git("checkout", "-q", "main", cwd=self.fix["repo"])
        with open(root_file, "a", encoding="utf-8") as file:
            file.write("main\n")
        _git("commit", "-qam", "main change", cwd=self.fix["repo"])
        _git("checkout", "-q", "line/demo", cwd=self.fix["line_wt"])
        marker = os.path.join(self.fix["line_wt"], "child.txt")
        with open(marker, "w", encoding="utf-8") as file:
            file.write("child\n")
        _git("add", "child.txt", cwd=self.fix["line_wt"])

        before = self.common_root_files()
        result = self.run_fenced(
            "git", "-C", self.fix["line_wt"], "-c", "user.email=f@example.com",
            "-c", "user.name=fence", "commit", "-qm", "fenced commit")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_fenced("git", "-C", self.fix["line_wt"], "rebase", "main")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_fenced(
            "git", "-C", self.fix["line_wt"], "branch", "tmp-fence-branch")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_fenced(
            "git", "-C", self.fix["line_wt"], "branch", "-d", "tmp-fence-branch")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_fenced("git", "-C", self.fix["line_wt"], "pack-refs", "--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.common_root_files(), before)

    def test_unmanaged_repository_path_remains_writable(self):
        target = os.path.join(self.directory.name, "outside-managed-repos")
        result = self.run_fenced("touch", target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(target))


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
        register_write_set_request_routes(app, self.runtime, lambda att_id, pending=None: None)

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

    def test_the_line_itself_files_a_write_set_request(self):
        self.db.add_attachment("kid-worker", self.kid["id"], "worker", "fake",
                               ["fake"], self.directory.name)
        target = os.path.join(self.directory.name, "x")
        response = self.client.post(
            f"/api/conversations/{self.kid['id']}/write-set",
            json={"path": target},
            headers=self.machine("kid-worker"))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["path"], target)
        self.assertEqual(body["requester"], "worker")
        pending = self.client.get(f"/api/conversations/{self.kid['id']}/write-set/request")
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["request"]["id"], body["id"])

    def test_a_captain_above_can_file_a_write_set_request(self):
        target = os.path.join(self.directory.name, "captain-requested")
        response = self.client.post(
            f"/api/conversations/{self.kid['id']}/write-set",
            json={"path": target},
            headers=self.machine("root-lead"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["path"], target)

    def test_a_second_write_set_request_while_pending_is_409(self):
        self.db.add_attachment("kid-worker", self.kid["id"], "worker", "fake",
                               ["fake"], self.directory.name)
        headers = self.machine("kid-worker")
        first = os.path.join(self.directory.name, "first")
        second = os.path.join(self.directory.name, "second")
        self.assertEqual(self.client.post(
            f"/api/conversations/{self.kid['id']}/write-set",
            json={"path": first}, headers=headers).status_code, 200)
        self.assertEqual(self.client.post(
            f"/api/conversations/{self.kid['id']}/write-set",
            json={"path": second}, headers=headers).status_code, 409)

    def test_an_unrelated_machine_cannot_file_a_request(self):
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

    def test_a_granted_path_is_reopened_after_the_repository_deny(self):
        target = os.path.join(self.directory.name, "granted-dir")
        os.makedirs(target)
        line = os.path.join(self.repo, "child-worktree")
        os.makedirs(line)
        self.client.post(f"/api/conversations/{self.kid['id']}/write-set",
                         json={"path": target})
        att = _att(line, conv_id=self.kid["id"],
                   grants=list_write_grants(self.db, self.kid["id"]))
        att["protected_roots"] = [self.repo]
        with patch.object(git_fence, "FENCE_ROOT",
                          os.path.join(self.directory.name, "fence-root")):
            argv = fence._bwrap_argv(att, ["cli"])
        binds = [(argv[i], argv[i + 1], argv[i + 2]) for i, value in enumerate(argv)
                 if value in ("--bind", "--ro-bind")]
        self.assertIn(("--ro-bind", self.repo, self.repo), binds)
        self.assertIn(("--bind", target, target), binds)
        self.assertGreater(binds.index(("--bind", target, target)),
                           binds.index(("--ro-bind", self.repo, self.repo)))


if __name__ == "__main__":
    unittest.main()
