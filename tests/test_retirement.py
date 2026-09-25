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
        self.runtime.presence = type(
            "Presence", (), {"is_working": lambda _self, att_id: False}
        )()
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
        self.assertIn("POST /api/conversations/{id}/attachments/close", resp.json()["detail"])

    def test_stop_processes_detaches_the_line_and_descendants_before_retiring(self):
        mid = self.child()
        grand = self.child("grand", parent=mid["id"])
        for conv_id, att_id in ((mid["id"], "mid-worker"), (grand["id"], "grand-worker")):
            owner = f"owner-{att_id}"
            self.db.add_attachment(
                att_id, conv_id, att_id, "fake", ["fake"], self.repo, owner
            )
            self.db.set_attachment_status(att_id, "running", owner)

            class Adapter:
                def __init__(adapter_self, adapter_id, adapter_owner):
                    adapter_self.att = {"runtime_owner": adapter_owner}
                    adapter_self.adapter_id = adapter_id
                    adapter_self.adapter_owner = adapter_owner

                async def stop(adapter_self):
                    self.db.set_attachment_status(
                        adapter_self.adapter_id, "detached", adapter_self.adapter_owner
                    )

            self.runtime.live[att_id] = Adapter(att_id, owner)

        resp = self.retire(mid["id"], include_children=True, stop_processes=True)

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(set(resp.json()["stopped"]), {"mid-worker", "grand-worker"})
        self.assertEqual(self.db.get_attachment("mid-worker")["status"], "detached")
        self.assertEqual(self.db.get_attachment("grand-worker")["status"], "detached")

    def test_stop_processes_refuses_only_a_live_process_mid_turn(self):
        mid = self.child()
        self.db.add_attachment(
            "mid-worker", mid["id"], "worker", "fake", ["fake"], self.repo, "owner-worker"
        )
        self.db.set_attachment_status("mid-worker", "running", "owner-worker")
        self.runtime.presence = type(
            "Presence", (), {"is_working": lambda _self, att_id: att_id == "mid-worker"}
        )()

        resp = self.retire(mid["id"], stop_processes=True)

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual([b["code"] for b in resp.json()["blockers"]], ["process_mid_turn"])
        self.assertEqual(self.db.get_attachment("mid-worker")["status"], "running")

    def test_stop_processes_does_not_detach_when_another_blocker_remains(self):
        mid = self.child()
        self.unmerged(mid["cwd"])
        owner = "owner-worker"
        self.db.add_attachment(
            "mid-worker", mid["id"], "worker", "fake", ["fake"], self.repo, owner
        )
        self.db.set_attachment_status("mid-worker", "running", owner)

        class Adapter:
            def __init__(adapter_self):
                adapter_self.att = {"runtime_owner": owner}
                adapter_self.stopped = False

            async def stop(adapter_self):
                adapter_self.stopped = True
                self.db.set_attachment_status("mid-worker", "detached", owner)

        adapter = Adapter()
        self.runtime.live["mid-worker"] = adapter
        resp = self.retire(mid["id"], stop_processes=True)

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertIn("unmerged_commits", [b["code"] for b in resp.json()["blockers"]])
        self.assertFalse(adapter.stopped)
        self.assertEqual(self.db.get_attachment("mid-worker")["status"], "running")

    def test_machine_unmerged_blocker_names_merge_and_person_asymmetry(self):
        mid = self.child()
        self.unmerged(mid["cwd"])

        machine = self.retire(mid["id"])
        self.assertEqual(machine.status_code, 409, machine.text)
        machine_blocker = next(
            b for b in machine.json()["blockers"] if b["code"] == "unmerged_commits"
        )
        self.assertIn("person may retire from the UI", machine_blocker["message"])
        self.assertIn("machine captain must merge first", machine_blocker["message"])

        person = self.retire(mid["id"], headers=self.human)
        self.assertEqual(person.status_code, 200, person.text)

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

    def test_detached_head_commits_count_as_unmerged_and_survive_discard(self):
        mid = self.child()
        _git("checkout", "-q", "--detach", cwd=mid["cwd"])
        with open(os.path.join(mid["cwd"], "detached.txt"), "w") as fh:
            fh.write("lost work\n")
        _git("add", "-A", cwd=mid["cwd"])
        _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
             "-m", "detached work", cwd=mid["cwd"])
        self.assertFalse(worktree_state(self.db, mid)["merged"])

        resp = self.retire(mid["id"], discard=True)

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertIn("unmerged_commits",
                      [blocker["code"] for blocker in resp.json()["blockers"]])
        self.assertTrue(os.path.isfile(os.path.join(mid["cwd"], "detached.txt")))

    def test_a_detached_head_at_a_merged_commit_still_retires(self):
        mid = self.child()
        _git("checkout", "-q", "--detach", cwd=mid["cwd"])
        self.assertTrue(worktree_state(self.db, mid)["merged"])

        resp = self.retire(mid["id"], discard=True)

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["worktree_removed"])
        self.assertFalse(os.path.exists(mid["cwd"]))

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

    def test_an_archived_child_does_not_require_include_children(self):
        mid = self.child()
        grand = self.child("grand", parent=mid["id"])
        self.assertEqual(self.retire(grand["id"]).status_code, 200)

        retired = self.retire(mid["id"])

        self.assertEqual(retired.status_code, 200, retired.text)
        self.assertEqual(retired.json()["archived_ids"], [mid["id"]])

    def test_clean_merged_worktree_still_retires_normally(self):
        mid = self.child()

        resp = self.retire(mid["id"])

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["worktree_removed"])
        self.assertFalse(os.path.exists(mid["cwd"]))

    def test_worktree_state_is_none_without_a_worktree_of_its_own(self):
        self.assertIsNone(worktree_state(self.db, self.db.get_conversation("root")))

    def test_a_detached_parent_checkout_is_still_a_real_merge_base(self):
        # Fable's B1: the parent checkout is detached, so its "branch" is the
        # literal HEAD; as a rev-list base inside the child worktree that
        # resolved to the child's own tip and proved everything merged.
        mid = self.child()
        self.unmerged(mid["cwd"])
        self.dirty(mid["cwd"])
        _git("checkout", "-q", "--detach", cwd=self.repo)
        self.addCleanup(_git, "checkout", "-q", "main", cwd=self.repo)

        state = worktree_state(self.db, self.db.get_conversation(mid["id"]))
        self.assertEqual(state["merged"], False)

        resp = self.retire(mid["id"], discard=True)
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertIn("unmerged_commits",
                      [b["code"] for b in resp.json()["blockers"]])
        self.assertTrue(os.path.exists(os.path.join(mid["cwd"], "scratch.txt")))
        self.assertTrue(os.path.exists(mid["cwd"]))


if __name__ == "__main__":
    unittest.main()
