"""Scratch worktrees: writable checkouts for integration builds (finding 2.15)."""

import os
import subprocess
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.fence_paths import write_set
from partyline.goal import register_goal_route
from partyline.hierarchy_routes import hierarchy_router
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime
from partyline.scratch_schema import MIGRATIONS as SCRATCH_MIGRATIONS
from partyline.scratch_worktrees import (
    SCRATCH_DIR,
    register_scratch_routes,
    sweep_scratch_worktrees,
)


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=t@example.com", "-c", "user.name=t", *args, cwd=cwd)


class ScratchWorktreesTest(unittest.TestCase):
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
        register_goal_route(app, self.runtime)
        register_scratch_routes(app, self.runtime)

        async def fake_start(att, **kwargs):
            return att

        register_conversation_routes(
            app, self.runtime, MediaStore(self.db, self.directory.name + "/media"),
            None, {}, {}, fake_start,
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(setattr, server, "runtime", server.runtime)
        server.runtime = self.runtime
        self.db.create_conversation("root", "Root")
        self.db.add_attachment("root-lead", "root", "terra", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='root-lead'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "root-lead")}
        self.client.headers.update(self.human)
        made = self.client.post("/api/conversations/root/children", json={"name": "kid"})
        self.assertEqual(made.status_code, 201, made.text)
        self.kid = made.json()["conversation"]
        self.worktree = self.kid["cwd"]

    def commit(self, message, filename="code.txt"):
        with open(os.path.join(self.worktree, filename), "a") as fh:
            fh.write(message + "\n")
        _git("add", "-A", cwd=self.worktree)
        _identity("commit", "-q", "-m", message, cwd=self.worktree)
        return _git("rev-parse", "HEAD", cwd=self.worktree).stdout.strip()

    def create(self, sha, repository=None, conv_id=None):
        body = {"sha": sha}
        if repository is not None:
            body["repository"] = repository
        return self.client.post(
            f"/api/conversations/{conv_id or self.kid['id']}/scratch-worktrees",
            json=body, headers=self.captain)

    def scratch_dir(self, sha, repo=None):
        return os.path.join(repo or self.repo, SCRATCH_DIR, sha)

    def test_creation_checks_out_writable_and_recorded_on_the_line(self):
        sha = self.commit("buildable work")
        made = self.create(sha)
        self.assertEqual(made.status_code, 201, made.text)
        body = made.json()
        self.assertEqual(body["path"], self.scratch_dir(sha))
        self.assertEqual(
            _git("rev-parse", "HEAD", cwd=body["path"]).stdout.strip(), sha)
        self.assertEqual(
            _git("rev-parse", "--abbrev-ref", "HEAD", cwd=body["path"]).stdout.strip(),
            "HEAD")  # detached checkout
        # excluded from the main checkout's git status, like .review
        self.assertEqual(_git("status", "--porcelain", cwd=self.repo).stdout.strip(), "")
        listed = self.client.get(
            f"/api/conversations/{self.kid['id']}/scratch-worktrees",
            headers=self.captain)
        self.assertEqual([row["path"] for row in listed.json()], [body["path"]])
        # creating the same SHA again hands back the same checkout
        again = self.create(sha)
        self.assertEqual(again.json()["path"], body["path"])
        self.assertEqual(len(listed.json()), 1)

    def test_a_subtree_repository_is_allowed_and_a_stranger_is_refused(self):
        other = os.path.join(self.directory.name, "other")
        os.makedirs(other)
        _git("init", "-q", "-b", "main", cwd=other)
        port = os.path.join(other, ".partyline-worktrees", "port")
        os.makedirs(port)
        self.db.create_conversation("port", "Port")
        self.db._exec("UPDATE conversations SET parent_id=?, cwd=? WHERE id='port'",
                      (self.kid["id"], port))
        with open(os.path.join(other, "f.txt"), "w") as fh:
            fh.write("portable\n")
        _git("add", "-A", cwd=other)
        _identity("commit", "-q", "-m", "portable work", cwd=other)
        sha = _git("rev-parse", "HEAD", cwd=other).stdout.strip()
        made = self.create(sha, repository=other)
        self.assertEqual(made.status_code, 201, made.text)
        self.assertEqual(made.json()["path"], self.scratch_dir(sha, other))
        stranger = os.path.join(self.directory.name, "stranger")
        os.makedirs(stranger)
        _git("init", "-q", "-b", "main", cwd=stranger)
        _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=stranger)
        stranger_sha = _git("rev-parse", "HEAD", cwd=stranger).stdout.strip()
        refused = self.create(stranger_sha, repository=stranger)
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertIn("subtree", refused.json()["detail"])
        self.assertFalse(os.path.isdir(self.scratch_dir(stranger_sha, stranger)))

    def test_the_fence_write_set_includes_scratch_but_not_review_paths(self):
        sha = self.commit("buildable work")
        made = self.create(sha)
        path = made.json()["path"]
        att = {"conv_id": self.kid["id"], "cwd": self.worktree,
               "scratch_worktrees": [{"conv_id": self.kid["id"], "sha": sha, "path": path}],
               "review_worktrees": [
                   {"conv_id": self.kid["id"], "sha": sha,
                    "path": os.path.join(self.repo, ".review", sha)}]}
        writable = [src for src, _dst, read_only in write_set(att) if not read_only]
        # the whole .scratch root is bound writable, so the build tree inside it
        # is writable, and the checkout's own git metadata is bound beside it
        self.assertIn(self.scratch_dir_root(), writable)
        gitdir = os.path.realpath(
            subprocess.run(["git", "rev-parse", "--git-dir"], cwd=path,
                           capture_output=True, text=True, check=True).stdout.strip())
        self.assertIn(gitdir, writable)
        scratch_carve = [src for src in writable
                         if src == self.scratch_dir_root() or f"/{SCRATCH_DIR}/" in src]
        self.assertTrue(scratch_carve)
        self.assertNotIn(os.path.join(self.repo, ".review", sha), scratch_carve)

    def scratch_dir_root(self, repo=None):
        return os.path.join(repo or self.repo, SCRATCH_DIR)

    def test_retirement_prunes_and_delete_drops_one_early(self):
        first = self.commit("first build")
        second = self.commit("second build")
        self.create(first)
        self.create(second)
        dropped = self.client.delete(
            f"/api/conversations/{self.kid['id']}/scratch-worktrees/{first}",
            headers=self.captain)
        self.assertEqual(dropped.status_code, 200, dropped.text)
        self.assertFalse(os.path.isdir(self.scratch_dir(first)))
        self.assertTrue(os.path.isdir(self.scratch_dir(second)))
        missing = self.client.delete(
            f"/api/conversations/{self.kid['id']}/scratch-worktrees/{first}",
            headers=self.captain)
        self.assertEqual(missing.status_code, 404, missing.text)
        # the line's own commits are unmerged; a person may still retire it
        retired = self.client.delete(f"/api/conversations/{self.kid['id']}",
                                     headers=self.human)
        self.assertEqual(retired.status_code, 200, retired.text)
        self.assertFalse(os.path.isdir(self.scratch_dir(second)))
        self.assertEqual(self.db._exec("SELECT path FROM scratch_worktrees").fetchall(), [])

    def test_the_startup_sweep_rules_orphans_by_their_record(self):
        first = self.commit("first build")
        second = self.commit("second build")
        self.create(first)
        self.create(second)
        # an unrecorded directory under .scratch with a full-SHA name
        orphan_sha = "a" * 40
        os.makedirs(self.scratch_dir(orphan_sha))
        sweep_scratch_worktrees(self.db, self.repo)
        self.assertTrue(os.path.isdir(self.scratch_dir(first)))  # live line: kept
        self.assertTrue(os.path.isdir(self.scratch_dir(second)))
        self.assertFalse(os.path.isdir(self.scratch_dir(orphan_sha)))  # no record: swept
        self.db.archive_conversation(self.kid["id"])
        sweep_scratch_worktrees(self.db, self.repo)
        self.assertFalse(os.path.isdir(self.scratch_dir(first)))  # line gone: swept
        self.assertFalse(os.path.isdir(self.scratch_dir(second)))
        self.assertEqual(self.db._exec("SELECT path FROM scratch_worktrees").fetchall(), [])

    def test_the_schema_migration_runs_twice(self):
        for _ in range(2):
            for migration in SCRATCH_MIGRATIONS:
                self.db._exec(migration)
        sha = self.commit("buildable work")
        self.assertEqual(self.create(sha).status_code, 201)
        self.assertEqual(
            self.db._exec("SELECT COUNT(*) AS n FROM scratch_worktrees").fetchone()["n"], 1)


if __name__ == "__main__":
    unittest.main()
