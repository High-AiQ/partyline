"""A captain asks for a restart; only a person may approve or decline it."""

import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, deployment
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.restart_requests import register_restart_request_routes, service_unit
from partyline.runtime import ChatRuntime


class RestartRequestTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.exits = []
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_restart_request_routes(
            app, self.runtime, {"fake": {"capabilities": {"resume": True}}},
            lambda: self.exits.append(True))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("cap", "line", "astra", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='cap'")
        self.db.add_attachment("wrk", "line", "luna", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='wrk'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "cap")}
        self.worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "wrk")}
        # These tests exercise the filing flow, not the deployment guard: the
        # running checkout (this worktree) has not moved since import, which
        # would otherwise refuse every request here with nothing-to-deploy.
        self.enterContext(patch.object(deployment, "_STARTUP", (None, None)))

    def file(self, headers, reason="1.19.1 is merged and pulled"):
        return self.client.post("/api/conversations/line/restart-request",
                                json={"reason": reason}, headers=headers)

    def test_a_captain_files_a_request_a_worker_cannot_and_the_line_hears_it(self):
        self.assertEqual(self.file(self.worker).status_code, 403)
        filed = self.file(self.captain)
        self.assertEqual(filed.status_code, 200, filed.text)
        self.assertEqual(filed.json()["requester"], "astra")
        self.assertIn("asks a person to restart partyline", self.db.list_messages("line")[-1]["body"])
        self.assertEqual(self.file(self.captain).status_code, 409)  # one at a time
        pending = self.client.get("/api/restart-request", headers=self.worker).json()
        self.assertEqual(pending["request"]["id"], filed.json()["id"])

    def test_only_a_person_decides_and_approval_plans_everyone_then_restarts(self):
        request_id = self.file(self.captain).json()["id"]
        self.assertEqual(self.client.post(f"/api/restart-request/{request_id}/approve",
                                          headers=self.captain).status_code, 403)
        self.runtime.live["cap"] = self.runtime.live["wrk"] = object()
        with patch("partyline.restart_requests.service_unit", return_value="partyline-x.service"), \
             patch("partyline.restart_requests.schedule_unit_restart", return_value=True) as sched:
            approved = self.client.post(f"/api/restart-request/{request_id}/approve",
                                        headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        sched.assert_called_once_with("partyline-x.service")
        self.assertIsNone(self.runtime.restart_request)
        self.assertIn("restart approved by @person", self.db.list_messages("line")[-1]["body"])
        plan = self.db.get_restart_plan()
        self.assertEqual(plan["mode"], "automatic")
        self.assertEqual(sorted(plan["attachment_ids"]), ["cap", "wrk"])
        self.assertEqual(self.client.get("/api/restart-request", headers=self.human).json(),
                         {"request": None})

    def test_declining_clears_the_request_and_says_so(self):
        request_id = self.file(self.captain).json()["id"]
        declined = self.client.delete(f"/api/restart-request/{request_id}", headers=self.human)
        self.assertEqual(declined.status_code, 200)
        self.assertIn("restart declined by @person", self.db.list_messages("line")[-1]["body"])
        self.assertEqual(self.client.delete(f"/api/restart-request/{request_id}",
                                            headers=self.human).status_code, 404)

    def test_the_unit_is_read_from_the_cgroup(self):
        self.assertIsInstance(service_unit(), (str, type(None)))
