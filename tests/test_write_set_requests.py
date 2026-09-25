"""A line asks for write-set scope; only a person may approve or decline it."""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.adapters import ADAPTER_METADATA
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.reattach import ResumedAttachment
from partyline.runtime import ChatRuntime
from partyline.write_set_requests import register_write_set_request_routes, resume_line_attachments
from partyline.write_set_routes import list_write_grants, write_set_router
from tests.test_server import FakeAdapter


class Recorder:
    def __init__(self, attachment, *, on_stop=None):
        self.att = attachment
        self.delivered = []
        self.stopped = False
        self._on_stop = on_stop

    async def deliver(self, messages):
        self.delivered.extend(messages)

    async def stop(self):
        self.stopped = True
        if self._on_stop is not None:
            await self._on_stop()


class WriteSetRequestTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.resumed = []
        metadata = {**ADAPTER_METADATA, "fake": {"capabilities": {"resume": True}}}
        metadata_patch = patch("partyline.write_set_requests.ADAPTER_METADATA", metadata)
        metadata_patch.start()
        self.addCleanup(metadata_patch.stop)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(write_set_router(self.runtime))
        register_write_set_request_routes(app, self.runtime, self._resume)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("cap", "line", "astra", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='cap'")
        self.db.add_attachment("wrk", "line", "worker", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='wrk'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "cap")}
        self.worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "wrk")}
        self.target = os.path.join(self.directory.name, "shared")

    async def _resume(self, att_id, pending=None):
        self.resumed.append(att_id)
        self.runtime.live[att_id] = FakeAdapter()
        return ResumedAttachment(FakeAdapter(), False)

    async def _resume_line(self, runtime, conv_id, resume):
        self.resumed.extend(["cap", "wrk"])
        return ["cap", "wrk"], []

    def file(self, headers, path=None, conv_id="line"):
        return self.client.post(
            f"/api/conversations/{conv_id}/write-set",
            json={"path": path or self.target},
            headers=headers)

    def audience_copies(self, att_id):
        return [m for m in self.db.list_messages("line")
                if m["audience_attachment_id"] == att_id]

    def public_notices(self, phrase):
        return [m for m in self.db.list_messages("line")
                if phrase in m["body"] and m["audience_attachment_id"] is None]

    def go_live(self, att_id):
        att = self.db.get_attachment(att_id)
        owner = att.get("runtime_owner") or f"owner-{att_id}"
        self.db._exec("UPDATE attachments SET runtime_owner=? WHERE id=?", (owner, att_id))
        att = self.db.get_attachment(att_id)

        async def on_stop():
            self.db.set_attachment_status(att_id, "exited", owner)

        recorder = Recorder(att, on_stop=on_stop)
        self.runtime.live[att_id] = recorder
        return recorder

    def test_a_worker_files_a_request_a_stranger_cannot_and_the_line_hears_it(self):
        self.db.create_conversation("stranger", "Stranger")
        self.db.add_attachment("other", "stranger", "other", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='other'")
        stranger = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "other")}
        self.assertEqual(self.file(stranger).status_code, 403)
        filed = self.file(self.worker)
        self.assertEqual(filed.status_code, 200, filed.text)
        notice = self.db.list_messages("line")[-1]
        self.assertIn("asks a person to grant write-set scope", notice["body"])
        self.assertEqual(self.file(self.worker).status_code, 409)

    def test_only_a_person_decides_and_approval_grants_and_resumes_the_line(self):
        request_id = self.file(self.worker).json()["id"]
        self.assertEqual(self.client.post(
            f"/api/conversations/line/write-set/request/{request_id}/approve",
            headers=self.worker).status_code, 403)
        cap = self.go_live("cap")
        wrk = self.go_live("wrk")
        approved = self.client.post(
            f"/api/conversations/line/write-set/request/{request_id}/approve",
            headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertTrue(cap.stopped)
        self.assertTrue(wrk.stopped)
        self.assertEqual(sorted(self.resumed), ["cap", "wrk"])
        grants = list_write_grants(self.db, "line")
        self.assertEqual([row["path"] for row in grants], [self.target])
        self.assertEqual(self.client.get(
            "/api/conversations/line/write-set/request", headers=self.human).json(),
                         {"request": None})

    def test_resume_line_detach_then_resumes_every_live_attachment(self):
        cap = self.go_live("cap")
        wrk = self.go_live("wrk")
        resumed, failed = asyncio.run(
            resume_line_attachments(self.runtime, "line", self._resume))
        self.assertEqual(resumed, ["cap", "wrk"])
        self.assertEqual(failed, [])
        self.assertTrue(cap.stopped)
        self.assertTrue(wrk.stopped)

    def test_approval_surfaces_a_resume_failure_and_still_resumes_the_rest(self):
        request_id = self.file(self.worker).json()["id"]
        self.go_live("cap")
        self.go_live("wrk")

        async def resume_with_backlog(runtime, att_id, resume, **kwargs):
            if att_id == "wrk":
                raise RuntimeError("resume broke")
            self.resumed.append(att_id)
            self.runtime.live[att_id] = FakeAdapter()
            return ResumedAttachment(FakeAdapter(), False)

        with patch("partyline.write_set_requests.resume_with_backlog", resume_with_backlog):
            approved = self.client.post(
                f"/api/conversations/line/write-set/request/{request_id}/approve",
                headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(self.resumed, ["cap"])
        notice = self.public_notices("approved by @person")[0]["body"]
        self.assertIn("could not resume @worker", notice)
        copies = self.audience_copies("wrk")
        self.assertIn("could not resume @worker", copies[0]["body"])

    def test_non_resumable_live_adapter_keeps_request_pending_without_grant_or_detach(self):
        request_id = self.file(self.worker).json()["id"]
        self.db.set_attachment_status("cap", "exited", None)
        self.db._exec("UPDATE attachments SET adapter='raw' WHERE id='wrk'")
        worker = self.go_live("wrk")
        metadata = {
            "fake": {"capabilities": {"resume": True}},
            "raw": {"capabilities": {"resume": False}},
        }
        with patch("partyline.write_set_requests.ADAPTER_METADATA", metadata):
            response = self.client.post(
                f"/api/conversations/line/write-set/request/{request_id}/approve",
                headers=self.human,
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("@worker (raw)", response.json()["detail"])
        self.assertFalse(worker.stopped)
        self.assertEqual(list_write_grants(self.db, "line"), [])
        pending = self.client.get(
            "/api/conversations/line/write-set/request", headers=self.human)
        self.assertEqual(pending.json()["request"]["id"], request_id)

    def test_machine_filed_bad_path_is_400(self):
        response = self.file(self.worker, path="relative/path")
        self.assertEqual(response.status_code, 400, response.text)

    def test_approve_and_decline_of_a_stale_request_id_is_404(self):
        request_id = self.file(self.worker).json()["id"]
        approved = self.client.post(
            f"/api/conversations/line/write-set/request/{request_id}/approve",
            headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(self.client.post(
            f"/api/conversations/line/write-set/request/{request_id}/approve",
            headers=self.human).status_code, 404)
        request_id = self.file(self.worker).json()["id"]
        self.assertEqual(self.client.delete(
            f"/api/conversations/line/write-set/request/{request_id}",
            headers=self.human).status_code, 200)
        self.assertEqual(self.client.delete(
            f"/api/conversations/line/write-set/request/{request_id}",
            headers=self.human).status_code, 404)

    def test_approval_privately_rings_the_requester_once(self):
        request_id = self.file(self.worker).json()["id"]
        wrk = self.go_live("wrk")
        self.go_live("cap")
        with patch("partyline.write_set_requests.resume_line_attachments", self._resume_line):
            approved = self.client.post(
                f"/api/conversations/line/write-set/request/{request_id}/approve",
                headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)

        copies = self.audience_copies("wrk")
        self.assertEqual(len(copies), 1)
        self.assertIn("approved by @person", copies[0]["body"])
        self.assertIsNone(copies[0]["source_attachment_id"])
        backlog_ids = [m["id"] for m in self.db.messages_after("line", 0, "worker", "wrk")]
        self.assertIn(copies[0]["id"], backlog_ids)

        ringed = [m for m in wrk.delivered if m.get("audience_attachment_id") == "wrk"]
        self.assertEqual(len(ringed), 1)
        self.assertEqual(len(self.public_notices("approved by @person")), 1)

    def test_decline_privately_rings_the_requester_once(self):
        request_id = self.file(self.worker).json()["id"]
        wrk = self.go_live("wrk")
        declined = self.client.delete(
            f"/api/conversations/line/write-set/request/{request_id}", headers=self.human)
        self.assertEqual(declined.status_code, 200, declined.text)
        copies = self.audience_copies("wrk")
        self.assertEqual(len(copies), 1)
        self.assertIn("declined by @person", copies[0]["body"])
        ringed = [m for m in wrk.delivered if m.get("audience_attachment_id") == "wrk"]
        self.assertEqual(len(ringed), 1)

    def test_outcome_rings_the_filing_attachment_not_an_exited_namesake(self):
        self.db.add_attachment("wrk-old", "line", "worker", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='wrk-old'")
        request_id = self.file(self.worker).json()["id"]
        wrk = self.go_live("wrk")
        declined = self.client.delete(
            f"/api/conversations/line/write-set/request/{request_id}", headers=self.human)
        self.assertEqual(declined.status_code, 200)
        self.assertEqual(self.audience_copies("wrk-old"), [])
        self.assertEqual(len(self.audience_copies("wrk")), 1)
        ringed = [m for m in wrk.delivered if m.get("audience_attachment_id") == "wrk"]
        self.assertEqual(len(ringed), 1)

    def file_on_child(self):
        self.db.create_conversation("child", "Child")
        self.db._exec("UPDATE conversations SET parent_id='line' WHERE id='child'")
        return self.client.post(
            "/api/conversations/child/write-set",
            json={"path": self.target},
            headers=self.captain).json()["id"]

    def test_cross_line_approval_rings_the_requester_on_its_home_line(self):
        request_id = self.file_on_child()
        cap = self.go_live("cap")
        with patch("partyline.write_set_requests.resume_line_attachments", self._resume_line):
            approved = self.client.post(
                f"/api/conversations/child/write-set/request/{request_id}/approve",
                headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual([m for m in self.db.list_messages("child")
                          if m["audience_attachment_id"]], [])
        self.assertEqual(len(self.audience_copies("cap")), 1)
        ringed = [m for m in cap.delivered if m.get("audience_attachment_id") == "cap"]
        self.assertEqual(len(ringed), 1)


if __name__ == "__main__":
    unittest.main()
