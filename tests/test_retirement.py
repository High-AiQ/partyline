"""Retirement: every blocker in one response, and discard only for merged worktrees."""

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
from partyline.goal import register_goal_route
from partyline.hierarchy_routes import hierarchy_router
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime
from partyline.worktree_lifecycle import worktree_state


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


class RetirementTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = os.path.join(self.directory.name, "repo")
        os.makedirs(self.repo)
        _git("init", "-q", "-b", "main", cwd=self.repo)
        _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "root", cwd=self.repo)
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
        self.addCleanup(setattr, server, "_start_attachment", server._start_attachment)
        server.runtime = self.runtime
        server._start_attachment = fake_start
        self.db.create_conversation("root", "Root")
        self.db.add_attachment("root-lead", "root", "terra", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='root-lead'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "root-lead")}

    def child(self, name="mid", parent="root"):
        made = self.client.post(f"/api/conversations/{parent}/children",
                                json={"name": name}, headers=self.human)
        self.assertEqual(made.status_code, 201, made.text)
        return made.json()["conversation"]

    def dirty(self, cwd, name="scratch.txt"):
        with open(os.path.join(cwd, name), "w") as fh:
            fh.write("wip")

    def unmerged(self, cwd):
        _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "unmerged", cwd=cwd)

    def retire(self, conv_id, headers=None, **params):
        query = "&".join(f"{k}={str(v).lower()}" for k, v in params.items())
        path = f"/api/conversations/{conv_id}" + (f"?{query}" if query else "")
        return self.client.delete(path, headers=headers or self.captain)

    def test_all_blockers_come_back_together_in_one_response(self):
        mid = self.child()
        with open(os.path.join(mid["cwd"], "scratch.txt"), "w") as fh:
            fh.write("wip")
        self.db._exec("UPDATE conversations SET goal=? WHERE id=?", ("finish it", mid["id"]))
        worker = self.client.post(f"/api/conversations/{mid['id']}/attachments",
                                  json={"name": "gemini", "adapter": "raw", "command": "sh"},
                                  headers=self.captain)
        self.assertEqual(worker.status_code, 200, worker.text)
        self.db._exec("UPDATE attachments SET status='running' WHERE name='gemini'")

        resp = self.retire(mid["id"])

        self.assertEqual(resp.status_code, 409, resp.text)
        codes = {blocker["code"] for blocker in resp.json()["blockers"]}
        self.assertEqual(codes, {"live_processes", "goal_not_cleared", "uncommitted_changes"})
        self.assertIn("live processes", resp.json()["detail"])
        self.assertIn("goal", resp.json()["detail"])
        self.assertIn("uncommitted changes", resp.json()["detail"])

    def test_discard_removes_a_merged_dirty_worktree(self):
        mid = self.child()
        self.dirty(mid["cwd"])
        self.assertEqual(worktree_state(self.db, mid)["merged"], True)

        resp = self.retire(mid["id"], discard=True)

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["worktree_removed"])
        self.assertFalse(os.path.exists(mid["cwd"]))

    def test_discard_is_refused_for_an_unmerged_branch(self):
        mid = self.child()
        self.unmerged(mid["cwd"])
        self.dirty(mid["cwd"])

        resp = self.retire(mid["id"], discard=True)

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertIn("unmerged_commits",
                      [blocker["code"] for blocker in resp.json()["blockers"]])
        self.assertTrue(os.path.isdir(mid["cwd"]))

    def test_a_person_may_discard_a_merged_dirty_worktree(self):
        mid = self.child()
        self.dirty(mid["cwd"])

        resp = self.retire(mid["id"], headers=self.human, discard=True)

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["worktree_removed"])
        self.assertFalse(os.path.exists(mid["cwd"]))

    def test_a_person_without_discard_still_keeps_the_dirty_worktree(self):
        mid = self.child()
        self.dirty(mid["cwd"])

        resp = self.retire(mid["id"], headers=self.human)

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(resp.json()["worktree_removed"])
        self.assertEqual(resp.json()["worktree_kept_reason"], "uncommitted changes")
        self.assertTrue(os.path.isdir(mid["cwd"]))

    def test_child_lines_block_unless_include_children(self):
        mid = self.child()
        self.child("grand", parent=mid["id"])

        blocked = self.retire(mid["id"])
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("child_lines", [b["code"] for b in blocked.json()["blockers"]])

        allowed = self.retire(mid["id"], include_children=True)
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertIn(mid["id"], allowed.json()["archived_ids"])

    def test_clean_merged_worktree_still_retires_normally(self):
        mid = self.child()

        resp = self.retire(mid["id"])

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["worktree_removed"])
        self.assertFalse(os.path.exists(mid["cwd"]))

    def test_worktree_state_is_none_without_a_worktree_of_its_own(self):
        self.assertIsNone(worktree_state(self.db, self.db.get_conversation("root")))


if __name__ == "__main__":
    unittest.main()
