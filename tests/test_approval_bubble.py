"""Human-gated requests filed below the root bubble to the root line (finding 2.12).

A child line's write-set, memory or restart request used to post only on that
line: the person — who talks to the root captain and never reads sublines —
found it by luck. The filing paths now post one ⚑ notice on the tree's root
and ring the root's captain; the staffing wake line counts what is still
pending across the subtree.
"""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, deployment
from partyline.approval_bubble import register_approval_routes
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.memory_requests import register_memory_request_routes
from partyline.restart_requests import register_restart_request_routes
from partyline.runtime import ChatRuntime
from partyline.staffing import staffing_line
from partyline.write_set_decisions import register_write_set_request_routes
from partyline.write_set_routes import write_set_router


class Recorder:
    def __init__(self, attachment):
        self.att = attachment
        self.delivered = []

    async def deliver(self, messages):
        self.delivered.extend(messages)
        return [message["id"] for message in messages]


class ApprovalBubbleTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(write_set_router(self.runtime))
        register_write_set_request_routes(app, self.runtime, self._resume)
        register_approval_routes(app, self.runtime)
        register_memory_request_routes(app, self.runtime, self._resume)
        register_restart_request_routes(
            app, self.runtime, {"fake": {"capabilities": {"resume": True}}}, lambda: None)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("root", "Root")
        self.db.create_conversation("kid", "Kid")
        self.db.create_conversation("grand", "Grand")
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='kid'")
        self.db._exec("UPDATE conversations SET parent_id='kid' WHERE id='grand'")
        self.repo = os.path.join(self.directory.name, "repo")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo,
                       check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "root"],
                       cwd=self.repo, check=True, capture_output=True)
        self.db.add_attachment("rootcap", "root", "terra", "fake", ["fake"], self.repo)
        self.db.add_attachment("rootwrk", "root", "roe", "fake", ["fake"], self.repo)
        self.db.add_attachment("digger", "grand", "dig", "fake", ["fake"], self.repo)
        self.db.add_attachment("solcap", "grand", "sol", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' "
                      "WHERE id IN ('rootcap','solcap')")
        self.db._exec("UPDATE attachments SET status='running' WHERE id IN ('rootwrk','digger')")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.dig = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "digger")}
        self.sol = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "solcap")}
        # These tests exercise filing, not the deployment guard.
        self.enterContext(patch.object(deployment, "_STARTUP", (None, None)))
        ceiling = patch("partyline.memory_requests.memory_ceiling", return_value=8 * 1024**3)
        ceiling.start()
        self.addCleanup(ceiling.stop)
        self.db.set_setting("default_process_memory_bytes", str(3 * 1024**3))
        self.recorder = Recorder(self.db.get_attachment("rootcap"))
        self.runtime.live["rootcap"] = self.recorder
        self.worker_recorder = Recorder(self.db.get_attachment("rootwrk"))
        self.runtime.live["rootwrk"] = self.worker_recorder

    async def _resume(self, att_id, _pending=None):  # filing tests never resume
        return object()

    def bubbles(self):
        return [m for m in self.db.list_messages("root")
                if "⚑ approval pending" in m["body"] and m["audience_attachment_id"] is None]

    def delivered_bubbles(self):
        return [m for m in self.recorder.delivered if "⚑ approval pending" in m["body"]]

    def file_write_set(self):
        response = self.client.post("/api/conversations/grand/write-set",
                                    json={"path": os.path.join(self.repo, "extra")}, headers=self.dig)
        self.file_write_set_request_id = response.json()["id"]
        return response

    def file_memory(self):
        made = self.client.post("/api/attachments/digger/memory-requests",
                                json={"requested_limit": "5G", "reason": "large test bundle"},
                                headers=self.dig)
        self.memory_request_id = made.json()["id"]
        return made

    def file_restart(self):
        return self.client.post("/api/conversations/grand/restart-request",
                                json={"reason": "1.19.1 is merged and pulled"}, headers=self.sol)

    def test_a_write_set_request_on_a_grandchild_bubbles_to_the_root(self):
        made = self.file_write_set()
        self.assertEqual(made.status_code, 200, made.text)
        found = self.bubbles()
        self.assertEqual(len(found), 1)
        body = found[0]["body"]
        self.assertIn("⚑ approval pending on «Grand»", body)
        self.assertIn(": write-set from @dig", body)
        self.assertIn("grant write scope for `", body)
        self.assertIn("extra`", body)  # the filed path, inside the repo
        self.assertIn("(approve: POST /api/conversations/grand/write-set/request/", body)
        self.assertIn("decline: POST /api/conversations/grand/write-set/request/", body)
        self.assertIn("@terra", body)  # the root captain is named
        self.assertEqual(len(self.delivered_bubbles()), 1)  # and its process was rung

    def test_a_memory_request_on_a_grandchild_bubbles_to_the_root(self):
        made = self.file_memory()
        self.assertEqual(made.status_code, 200, made.text)
        found = self.bubbles()
        self.assertEqual(len(found), 1)
        body = found[0]["body"]
        self.assertIn(": memory from @dig", body)
        self.assertIn("5G memory cap for ＠dig: large test bundle", body)
        self.assertIn("(approve: POST /api/memory-requests/", body)
        self.assertIn("decline: DELETE /api/memory-requests/", body)
        self.assertIn("@terra", body)
        self.assertEqual(len(self.delivered_bubbles()), 1)

    def test_a_restart_request_on_a_grandchild_bubbles_to_the_root(self):
        made = self.file_restart()
        self.assertEqual(made.status_code, 200, made.text)
        found = self.bubbles()
        self.assertEqual(len(found), 1)
        body = found[0]["body"]
        self.assertIn(": restart from @sol", body)
        self.assertIn("1.19.1 is merged and pulled", body)
        self.assertIn("(approve: POST /api/restart-request/", body)
        self.assertIn("decline: DELETE /api/restart-request/", body)
        self.assertIn("@terra", body)
        self.assertEqual(len(self.delivered_bubbles()), 1)

    def test_a_request_on_the_root_itself_does_not_bubble(self):
        terra = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "rootcap")}
        made = self.client.post("/api/conversations/root/write-set",
                                json={"path": os.path.join(self.repo, "extra")}, headers=terra)
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(self.bubbles(), [])
        self.assertIn("asks to grant write-set scope",
                      " ".join(m["body"] for m in self.db.list_messages("root")))

    def test_without_a_root_captain_the_notice_still_posts_unaddressed(self):
        self.db._exec("DELETE FROM attachments WHERE id='rootcap'")
        self.runtime.live.pop("rootcap")
        made = self.file_write_set()
        self.assertEqual(made.status_code, 200, made.text)
        found = self.bubbles()
        self.assertEqual(len(found), 1)
        self.assertNotIn("@terra", found[0]["body"])

    def test_a_reason_cannot_address_the_root_line_through_the_bubble(self):
        # the detail is child-authored free text on a force-routed notice: a
        # live @all or root handle in it would let a child ring the root line
        made = self.client.post("/api/attachments/digger/memory-requests",
                                json={"requested_limit": "5G",
                                      "reason": "bundle for @all and @terra to see"},
                                headers=self.dig)
        self.assertEqual(made.status_code, 200, made.text)
        found = self.bubbles()
        self.assertEqual(len(found), 1)
        body = found[0]["body"]
        self.assertNotIn("@all", body)  # defused in the stored notice itself
        self.assertIn("＠all and ＠terra to see", body)
        self.assertIn("from @dig", body)  # the deliberate requester name survives
        self.assertIn("@terra", body)  # and so does the deliberate captain ring
        self.assertEqual(len(self.delivered_bubbles()), 1)  # the captain, once
        self.assertEqual(self.worker_recorder.delivered, [])  # @all rang nobody extra

    def test_approvals_endpoint_lists_subtree_rows_for_people(self):
        self.file_write_set()
        self.file_memory()
        seen = self.client.get("/api/conversations/root/approvals", headers=self.human)
        self.assertEqual(seen.status_code, 200, seen.text)
        rows = seen.json()["approvals"]
        self.assertEqual([row["kind"] for row in rows], ["write-set", "memory"])
        self.assertEqual([row["line"] for row in rows], ["Grand", "Grand"])
        self.assertEqual([row["requester"] for row in rows], ["dig", "dig"])
        self.assertIn(rows[0]["request_id"], (self.file_write_set_request_id,))
        self.assertEqual(rows[1]["request_id"], self.memory_request_id)
        approve_paths = [row["approve"] for row in rows]
        self.assertIn("/api/conversations/grand/write-set/request/", approve_paths[0])
        self.assertTrue(approve_paths[1].startswith("/api/memory-requests/"))
        self.assertTrue(all(row["decline"] for row in rows))

    def test_approvals_endpoint_is_people_only_and_covers_the_whole_subtree(self):
        # a request on the grandchild is visible from the root; decided ones drop out
        self.file_write_set()
        dig = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "digger")}
        seen = self.client.get("/api/conversations/root/approvals", headers=dig)
        self.assertEqual(seen.status_code, 403, seen.text)
        grant = self.db._exec(
            "SELECT id FROM conversation_write_grant_requests WHERE conv_id='grand'"
        ).fetchone()
        declined = self.client.delete(
            f"/api/conversations/grand/write-set/request/{grant['id']}", headers=self.human)
        self.assertEqual(declined.status_code, 200, declined.text)
        self.assertEqual(
            self.client.get("/api/conversations/root/approvals",
                            headers=self.human).json()["approvals"], [])

    def test_the_staffing_line_counts_pending_across_the_subtree_and_drops_on_decision(self):
        self.assertNotIn("approvals pending",
                         staffing_line(self.db, "root", runtime=self.runtime))
        self.assertEqual(self.file_write_set().status_code, 200)
        self.assertEqual(self.file_memory().status_code, 200)
        self.assertEqual(self.file_restart().status_code, 200)
        for conv_id in ("root", "kid"):  # the whole subtree, from any captain above
            line = staffing_line(self.db, conv_id, runtime=self.runtime)
            self.assertIn("approvals pending: 3", line)
            self.assertIn("«Grand» write-set", line)
            self.assertIn("«Grand» memory", line)
            self.assertIn("«Grand» restart", line)
        grant = self.db._exec("SELECT id FROM conversation_write_grant_requests "
                              "WHERE conv_id='grand'").fetchone()
        declined = self.client.delete(
            f"/api/conversations/grand/write-set/request/{grant['id']}", headers=self.human)
        self.assertEqual(declined.status_code, 200, declined.text)
        memory = self.db._exec(
            "SELECT id FROM memory_limit_requests WHERE conv_id='grand'").fetchone()
        denied = self.client.delete(
            f"/api/memory-requests/{memory['id']}", headers=self.human)
        self.assertEqual(denied.status_code, 200, denied.text)
        self.assertIn("approvals pending: 1 («Grand» restart)",
                      staffing_line(self.db, "root", runtime=self.runtime))


if __name__ == "__main__":
    unittest.main()
