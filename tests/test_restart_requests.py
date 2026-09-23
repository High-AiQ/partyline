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


class Recorder:
    def __init__(self, attachment):
        self.att = attachment
        self.delivered = []

    async def deliver(self, messages):
        self.delivered.extend(messages)


class OrderingSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


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

    def go_live(self, att_id):
        recorder = Recorder(self.db.get_attachment(att_id))
        self.runtime.live[att_id] = recorder
        return recorder

    def file(self, headers, reason="1.19.1 is merged and pulled"):
        return self.client.post("/api/conversations/line/restart-request",
                                json={"reason": reason}, headers=headers)

    def audience_copies(self, att_id):
        return [m for m in self.db.list_messages("line")
                if m["audience_attachment_id"] == att_id]

    def public_notices(self, phrase):
        return [m for m in self.db.list_messages("line")
                if phrase in m["body"] and m["audience_attachment_id"] is None]

    def test_a_captain_files_a_request_a_worker_cannot_and_the_line_hears_it(self):
        self.assertEqual(self.file(self.worker).status_code, 403)
        filed = self.file(self.captain)
        self.assertEqual(filed.status_code, 200, filed.text)
        self.assertEqual(filed.json()["requester"], "astra")
        notice = self.db.list_messages("line")[-1]
        self.assertIn("asks a person to restart partyline", notice["body"])
        self.assertEqual(notice["source_attachment_id"], "cap")
        self.assertEqual(self.file(self.captain).status_code, 409)  # one at a time
        pending = self.client.get("/api/restart-request", headers=self.worker).json()
        self.assertEqual(pending["request"]["id"], filed.json()["id"])

    def test_only_a_person_decides_and_approval_plans_everyone_then_restarts(self):
        request_id = self.file(self.captain).json()["id"]
        self.assertEqual(self.client.post(f"/api/restart-request/{request_id}/approve",
                                          headers=self.captain).status_code, 403)
        self.go_live("cap")
        self.go_live("wrk")
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

    def test_approval_privately_rings_the_requester_once_before_shutdown(self):
        request_id = self.file(self.captain).json()["id"]
        cap = self.go_live("cap")
        wrk = self.go_live("wrk")
        sock = OrderingSocket()
        self.runtime.sockets["line"] = {sock}
        with patch("partyline.restart_requests.service_unit", return_value="partyline-x.service"), \
             patch("partyline.restart_requests.schedule_unit_restart", return_value=True):
            approved = self.client.post(f"/api/restart-request/{request_id}/approve",
                                        headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)

        copies = self.audience_copies("cap")
        self.assertEqual(len(copies), 1, "exactly one private copy for the requester")
        self.assertIn("restart approved", copies[0]["body"])
        # The actor is the person, so the PR #225 self-echo rule must not hide
        # this notice from the requester that filed the request.
        self.assertIsNone(copies[0]["source_attachment_id"])
        backlog_ids = [m["id"] for m in self.db.messages_after("line", 0, "astra", "cap")]
        self.assertIn(copies[0]["id"], backlog_ids,
                      "the requester must see its outcome on resume")

        ringed = [m for m in cap.delivered if m["audience_attachment_id"] == "cap"]
        self.assertEqual(len(ringed), 1, "the requester is rung once, never in a loop")
        self.assertEqual([m for m in wrk.delivered if m.get("audience_attachment_id")], [])

        public = self.public_notices("restart approved by @person")
        self.assertEqual(len(public), 1, "the public notice for humans is kept")

        private_at = next(
            i for i, payload in enumerate(sock.sent)
            if payload.get("type") == "message"
            and payload.get("message", {}).get("audience_attachment_id") == "cap"
        )
        shutdown_at = next(
            i for i, payload in enumerate(sock.sent) if payload.get("type") == "shutdown"
        )
        self.assertLess(private_at, shutdown_at,
                        "the requester's copy is posted before the shutdown sequence")

    def test_decline_privately_rings_the_requester_once(self):
        request_id = self.file(self.captain).json()["id"]
        cap = self.go_live("cap")
        declined = self.client.delete(f"/api/restart-request/{request_id}", headers=self.human)
        self.assertEqual(declined.status_code, 200, declined.text)

        copies = self.audience_copies("cap")
        self.assertEqual(len(copies), 1, "exactly one private copy for the requester")
        self.assertIn("restart declined", copies[0]["body"])
        self.assertIsNone(copies[0]["source_attachment_id"],
                          "the person decided; self-echo must not hide it from the requester")
        backlog_ids = [m["id"] for m in self.db.messages_after("line", 0, "astra", "cap")]
        self.assertIn(copies[0]["id"], backlog_ids)

        ringed = [m for m in cap.delivered if m["audience_attachment_id"] == "cap"]
        self.assertEqual(len(ringed), 1, "the requester is rung once, never in a loop")
        self.assertEqual(len(self.public_notices("restart declined by @person")), 1)

    def test_outcome_rings_the_filing_attachment_not_an_exited_namesake(self):
        # An older exited row may share the handle; only the attachment that
        # filed the request is the requester.
        self.db.add_attachment("cap-old", "line", "astra", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='cap-old'")
        self.db._exec("UPDATE attachments SET created_at=created_at-100 WHERE id='cap-old'")
        request_id = self.file(self.captain).json()["id"]
        cap = self.go_live("cap")
        declined = self.client.delete(f"/api/restart-request/{request_id}", headers=self.human)
        self.assertEqual(declined.status_code, 200, declined.text)

        self.assertEqual(self.audience_copies("cap-old"), [],
                         "the exited namesake must not capture the outcome")
        copies = self.audience_copies("cap")
        self.assertEqual(len(copies), 1, "the filing attachment is ringed exactly once")
        ringed = [m for m in cap.delivered if m["audience_attachment_id"] == "cap"]
        self.assertEqual(len(ringed), 1)

    def test_a_human_filed_request_rings_no_same_named_process(self):
        self.db.add_attachment("pclone", "line", "person", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='pclone'")
        filed = self.file(self.human)
        self.assertEqual(filed.status_code, 200, filed.text)
        self.assertIsNone(filed.json()["requester_attachment_id"],
                          "a person is not an attachment")
        pclone = self.go_live("pclone")
        declined = self.client.delete(f"/api/restart-request/{filed.json()['id']}",
                                      headers=self.human)
        self.assertEqual(declined.status_code, 200, declined.text)
        self.assertEqual(self.audience_copies("pclone"), [],
                         "a human-filed request must not target a same-named process")
        self.assertEqual(pclone.delivered, [])

    def file_on_child(self):
        # A captain may file on a descendant line; the requester still lives at home.
        self.db.create_conversation("child", "Child")
        self.db._exec("UPDATE conversations SET parent_id='line' WHERE id='child'")
        filed = self.client.post("/api/conversations/child/restart-request",
                                 json={"reason": "deploy to the child"}, headers=self.captain)
        self.assertEqual(filed.status_code, 200, filed.text)
        return filed.json()["id"]

    def audience_copies_on(self, conv_id, att_id):
        return [m for m in self.db.list_messages(conv_id)
                if m["audience_attachment_id"] == att_id]

    def stranded_copies_on(self, conv_id):
        return [m for m in self.db.list_messages(conv_id)
                if m["audience_attachment_id"]]

    def test_cross_line_approval_rings_the_requester_on_its_home_line(self):
        request_id = self.file_on_child()
        cap = self.go_live("cap")
        self.go_live("wrk")
        with patch("partyline.restart_requests.service_unit", return_value="partyline-x.service"), \
             patch("partyline.restart_requests.schedule_unit_restart", return_value=True):
            approved = self.client.post(f"/api/restart-request/{request_id}/approve",
                                        headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)

        self.assertEqual(self.stranded_copies_on("child"), [],
                         "the private copy must not be stranded on the requested line")
        home = self.audience_copies_on("line", "cap")
        self.assertEqual(len(home), 1, "the requester is ringed on its home line, once")
        ringed = [m for m in cap.delivered if m["audience_attachment_id"] == "cap"]
        self.assertEqual(len(ringed), 1)
        public = [m for m in self.db.list_messages("child")
                  if "restart approved by @person" in m["body"]
                  and m["audience_attachment_id"] is None]
        self.assertEqual(len(public), 1, "the public notice stays on the requested line")

    def test_cross_line_decline_rings_the_requester_on_its_home_line(self):
        request_id = self.file_on_child()
        cap = self.go_live("cap")
        declined = self.client.delete(f"/api/restart-request/{request_id}", headers=self.human)
        self.assertEqual(declined.status_code, 200, declined.text)

        self.assertEqual(self.stranded_copies_on("child"), [],
                         "the private copy must not be stranded on the requested line")
        home = self.audience_copies_on("line", "cap")
        self.assertEqual(len(home), 1, "the requester is ringed on its home line, once")
        ringed = [m for m in cap.delivered if m["audience_attachment_id"] == "cap"]
        self.assertEqual(len(ringed), 1)
        public = [m for m in self.db.list_messages("child")
                  if "restart declined by @person" in m["body"]
                  and m["audience_attachment_id"] is None]
        self.assertEqual(len(public), 1, "the public notice stays on the requested line")

    def test_declining_clears_the_request_and_says_so(self):
        request_id = self.file(self.captain).json()["id"]
        self.go_live("cap")
        declined = self.client.delete(f"/api/restart-request/{request_id}", headers=self.human)
        self.assertEqual(declined.status_code, 200)
        self.assertIn("restart declined by @person", self.db.list_messages("line")[-1]["body"])
        self.assertEqual(self.client.delete(f"/api/restart-request/{request_id}",
                                            headers=self.human).status_code, 404)

    def test_the_unit_is_read_from_the_cgroup(self):
        self.assertIsInstance(service_unit(), (str, type(None)))
