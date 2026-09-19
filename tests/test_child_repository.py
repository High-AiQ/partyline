"""Cross-repository births: ChildIn.repository places a child under another git repository."""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline import line_worktree as line_worktree_module
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.goal import register_goal_route
from partyline.hierarchy_routes import hierarchy_router
from partyline.line_worktree import WORKTREES_DIR
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=t@example.com", "-c", "user.name=t", *args, cwd=cwd)


class ChildRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

        def plain_repo(name):
            repo = os.path.join(self.directory.name, name)
            os.makedirs(repo)
            _git("init", "-q", "-b", "main", cwd=repo)
            _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=repo)
            return repo

        self.parent_repo = plain_repo("parent")
        self.other_repo = plain_repo("other")
        self.plain_dir = os.path.join(self.directory.name, "not-a-repo")
        os.makedirs(self.plain_dir)

        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        register_goal_route(app, self.runtime)

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
        self.db.add_attachment("root-lead", "root", "terra", "fake", ["fake"], self.parent_repo)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='root-lead'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.client.headers.update(self.human)
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "root-lead")}

    def child(self, name, headers=None, **fields):
        return self.client.post(
            "/api/conversations/root/children", json={"name": name, **fields},
            headers=headers or self.captain)

    def other_head(self):
        return _git("rev-parse", "HEAD", cwd=self.other_repo).stdout.strip()

    def system_messages(self, conv_id):
        rows = self.db._exec(
            "SELECT body FROM messages WHERE conv_id=? AND sender_type='system' ORDER BY id",
            (conv_id,),
        ).fetchall()
        return [row["body"] for row in rows]

    def test_a_child_is_placed_under_the_supplied_repository(self):
        made = self.child("fix", repository=self.other_repo)
        self.assertEqual(made.status_code, 201, made.text)
        conversation = made.json()["conversation"]
        expected = os.path.join(self.other_repo, WORKTREES_DIR, "fix")
        self.assertEqual(conversation["cwd"], expected)
        self.assertTrue(os.path.isdir(expected))
        self.assertEqual(_git("rev-parse", "HEAD", cwd=expected).stdout.strip(), self.other_head())
        self.assertEqual(
            _git("rev-parse", "line/fix", cwd=self.other_repo).stdout.strip(), self.other_head())
        notice = " ".join(self.system_messages(conversation["id"]))
        self.assertIn(expected, notice)  # the birth notice names the other repository
        self.assertIn("base checkout:", notice)  # it describes the target, not the parent

    def test_the_branch_lands_in_the_target_repository_not_the_parents(self):
        made = self.child("fix", repository=self.other_repo)
        self.assertEqual(made.status_code, 201, made.text)
        self.assertIn("line/fix", _git("branch", "--list", "line/fix", cwd=self.other_repo).stdout)
        self.assertNotIn("line/fix",
                         _git("branch", "--list", "line/fix", cwd=self.parent_repo).stdout)
        self.assertFalse(os.path.isdir(os.path.join(self.parent_repo, WORKTREES_DIR, "fix")))

    def test_invalid_and_non_git_targets_fail_safely(self):
        before = self.client.get("/api/conversations/root/children").json()
        relative = self.child("fix", repository="relative/path")
        self.assertEqual(relative.status_code, 400, relative.text)
        self.assertIn("absolute path", relative.json()["detail"])
        not_git = self.child("fix", repository=self.plain_dir)
        self.assertEqual(not_git.status_code, 400, not_git.text)
        self.assertIn("not inside a git repository", not_git.json()["detail"])
        self.assertEqual(self.client.get("/api/conversations/root/children").json(), before)
        self.assertFalse(os.path.isdir(os.path.join(self.parent_repo, WORKTREES_DIR)))

    def test_upstream_base_resolves_against_the_target_repository(self):
        origin = os.path.join(self.directory.name, "other-origin.git")
        _git("init", "-q", "--bare", "-b", "main", origin, cwd=self.directory.name)
        _git("remote", "add", "origin", origin, cwd=self.other_repo)
        _git("push", "-q", "-u", "origin", "main", cwd=self.other_repo)
        _git("remote", "set-head", "origin", "-a", cwd=self.other_repo)
        pusher = os.path.join(self.directory.name, "pusher")
        _git("clone", "-q", origin, pusher, cwd=self.directory.name)
        with open(os.path.join(pusher, "new.txt"), "w") as fh:
            fh.write("later work\n")
        _git("add", "-A", cwd=pusher)
        _identity("commit", "-q", "-m", "later work", cwd=pusher)
        _git("push", "-q", "origin", "main", cwd=pusher)
        origin_main = _git("rev-parse", "main", cwd=origin).stdout.strip()

        made = self.child("fix", repository=self.other_repo, base="upstream")
        self.assertEqual(made.status_code, 201, made.text)
        conversation = made.json()["conversation"]
        self.assertEqual(_git("rev-parse", "HEAD", cwd=conversation["cwd"]).stdout.strip(),
                         origin_main)
        self.assertNotEqual(_git("rev-parse", "HEAD", cwd=conversation["cwd"]).stdout.strip(),
                            self.other_head())

    def test_the_default_still_places_into_the_parents_repository(self):
        made = self.child("kid")
        self.assertEqual(made.status_code, 201, made.text)
        expected = os.path.join(self.parent_repo, WORKTREES_DIR, "kid")
        self.assertEqual(made.json()["conversation"]["cwd"], expected)
        self.assertTrue(os.path.isdir(expected))

    def test_capability_checks_are_unchanged_for_cross_repository_births(self):
        self.db.add_attachment("root-worker", "root", "dig", "fake", ["fake"], self.parent_repo)
        worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "root-worker")}
        made = self.child("fix", headers=worker, repository=self.other_repo)
        self.assertEqual(made.status_code, 403, made.text)
        self.assertFalse(os.path.isdir(os.path.join(self.other_repo, WORKTREES_DIR)))

    def test_a_failed_explicit_repository_placement_fails_and_rolls_back(self):
        original = line_worktree_module._git

        def add_fails(*args, cwd):
            if args[:2] == ("worktree", "add"):
                return subprocess.CompletedProcess(args, 128, "", "fatal: cannot create")
            return original(*args, cwd=cwd)

        with patch.object(line_worktree_module, "_git", side_effect=add_fails):
            made = self.child("fix", repository=self.other_repo)
        self.assertEqual(made.status_code, 409, made.text)
        self.assertIn("could not be created", made.json()["detail"])
        # no orphan line quietly seated in the parent's checkout instead
        self.assertEqual(self.client.get("/api/conversations/root/children").json(), [])
        self.assertFalse(
            os.path.isdir(os.path.join(self.other_repo, WORKTREES_DIR, "fix")))


if __name__ == "__main__":
    unittest.main()
