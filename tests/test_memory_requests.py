"""Request decisions enforce role, ceiling and replacement-resume rules."""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline.auth_guard import Principal
from partyline.adapters import ADAPTER_METADATA
from partyline.db import Db
from partyline.memory_requests import register_memory_request_routes
from partyline.resource_budget import Host, claim_resume, refusal
from partyline.runtime import ChatRuntime


class MemoryRequestTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Db(f"{self.temp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.runtime.broadcast = AsyncMock()
        self.db.create_conversation("line", "Line", captain_mode="orchestrator")
        self.db.add_attachment("worker", "line", "worker", "fake", ["fake"], self.temp.name)
        self.db.add_attachment("captain", "line", "captain", "fake", ["fake"], self.temp.name)
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='captain'")
        self.actor = Principal(kind="machine", name="worker", conv_id="line", attachment_id="worker")
        self.resumed = []
        app = FastAPI()

        @app.middleware("http")
        async def principal(request, call_next):
            request.state.principal = self.actor
            return await call_next(request)

        async def resume(ident, _pending=None):
            self.resumed.append((ident, ident in self.runtime.reattaching))
            self.runtime.live[ident] = SimpleNamespace(att=self.db.get_attachment(ident))
            return object()

        register_memory_request_routes(app, self.runtime, resume)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.host = patch("partyline.memory_requests.memory_ceiling", return_value=8 * 1024**3)
        self.host.start()
        self.addCleanup(self.host.stop)
        self.db.set_setting("memory_captain_ceiling_bytes", str(6 * 1024**3))
        self.db.set_setting("default_process_memory_bytes", str(3 * 1024**3))
        self.db.set_setting("memory_reservation_bytes", str(1024**3))
        self.adapter_metadata = patch.dict(
            ADAPTER_METADATA, {"fake": {"capabilities": {"resume": True}}}
        )
        self.adapter_metadata.start()
        self.addCleanup(self.adapter_metadata.stop)
        async def resume_backlog(runtime, ident, resume):
            return await resume(ident, [])
        self.resume_backlog = patch(
            "partyline.memory_requests.resume_with_backlog", side_effect=resume_backlog
        )
        self.resume_backlog.start()
        self.addCleanup(self.resume_backlog.stop)

    def file(self, amount="5G"):
        return self.client.post("/api/attachments/worker/memory-requests", json={
            "requested_limit": amount, "reason": "large test bundle",
        })

    def subtree(self):
        """A child line under 'line' with its own running worker attachment."""
        self.db.create_conversation("sub", "Sub", captain_mode="orchestrator")
        self.db._exec("UPDATE conversations SET parent_id='line' WHERE id='sub'")
        self.db.add_attachment("subworker", "sub", "subworker", "fake", ["fake"], self.temp.name)
        self.db._exec("UPDATE attachments SET status='running' WHERE id='subworker'")

    def file_as(self, actor, att_id, amount="5G"):
        self.actor = actor
        return self.client.post(f"/api/attachments/{att_id}/memory-requests", json={
            "requested_limit": amount, "reason": "large test bundle",
        })

    def captain(self, conv_id="line", att_id="captain"):
        return Principal(kind="machine", name="captain", conv_id=conv_id,
                         attachment_id=att_id, is_lead=True)

    def test_captain_files_for_subtree_worker_and_approves_within_ceiling(self):
        self.subtree()
        filed = self.file_as(self.captain(), "subworker")
        self.assertEqual(filed.status_code, 200, filed.text)
        approved = self.client.post(f"/api/memory-requests/{filed.json()['id']}/approve")
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(self.db.get_attachment("subworker")["memory_limit"], "5G")
        self.assertEqual(self.resumed, [("subworker", True)])

    def test_captain_filed_above_ceiling_for_subtree_worker_needs_a_person(self):
        self.subtree()
        filed = self.file_as(self.captain(), "subworker", "7G")
        self.assertEqual(filed.status_code, 200, filed.text)
        request_id = filed.json()["id"]
        self.assertEqual(
            self.client.post(f"/api/memory-requests/{request_id}/approve").status_code, 403)
        self.actor = Principal(kind="user", name="person", user_id=1)
        approved = self.client.post(f"/api/memory-requests/{request_id}/approve")
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(self.db.get_attachment("subworker")["memory_limit"], "7G")

    def test_captain_that_filed_for_another_process_can_decline_it(self):
        self.subtree()
        filed = self.file_as(self.captain(), "subworker")
        self.assertEqual(
            self.client.delete(f"/api/memory-requests/{filed.json()['id']}").status_code, 200)
        self.assertIsNone(
            self.client.get("/api/conversations/sub/memory-request").json()["request"])

    def test_captain_cannot_file_for_attachment_outside_its_scope(self):
        self.db.create_conversation("elsewhere", "Elsewhere", captain_mode="orchestrator")
        self.db.add_attachment("stranger", "elsewhere", "stranger", "fake", ["fake"],
                               self.temp.name)
        self.db._exec("UPDATE attachments SET status='running' WHERE id='stranger'")
        self.assertEqual(self.file_as(self.captain(), "stranger").status_code, 403)

    def test_captain_approves_under_ceiling_releases_lease_and_resumes(self):
        self.assertEqual(self.file().status_code, 200)
        pending = self.client.get("/api/conversations/line/memory-request").json()["request"]
        self.actor = Principal(kind="machine", name="captain", conv_id="line",
                               attachment_id="captain", is_lead=True)
        response = self.client.post(f"/api/memory-requests/{pending['id']}/approve")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.get_attachment("worker")["memory_limit"], "5G")
        self.assertEqual(self.resumed, [("worker", True)])
        self.assertNotIn("worker", self.runtime.reattaching)

    def test_above_captain_ceiling_escalates_to_person(self):
        self.assertEqual(self.file("7G").status_code, 200)
        pending = self.client.get("/api/conversations/line/memory-request").json()["request"]
        self.actor = Principal(kind="machine", name="captain", conv_id="line",
                               attachment_id="captain", is_lead=True)
        self.assertEqual(self.client.post(f"/api/memory-requests/{pending['id']}/approve").status_code, 403)
        self.actor = Principal(kind="user", name="person", user_id=1)
        approved = self.client.post(f"/api/memory-requests/{pending['id']}/approve")
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(self.db.get_attachment("worker")["memory_limit"], "7G")
        self.assertEqual(self.resumed, [("worker", True)])

    def test_person_can_approve_16g_on_large_host_but_small_host_clamps_ceiling(self):
        from partyline.resource_budget import GIB, memory_ceiling

        self.host.stop()
        with patch.dict("os.environ"):
            os.environ.pop("PARTYLINE_MAX_PROCESS_MEMORY_LIMIT", None)
            with patch("partyline.resource_budget.host_resources", return_value=Host(4, 32 * GIB)):
                self.assertEqual(memory_ceiling(), 16 * GIB)
                response = self.file("16G")
                self.assertEqual(response.status_code, 200, response.text)
                self.actor = Principal(kind="user", name="person", user_id=1)
                approved = self.client.post(f"/api/memory-requests/{response.json()['id']}/approve")
                self.assertEqual(approved.status_code, 200, approved.text)
                self.assertEqual(self.db.get_attachment("worker")["memory_limit"], "16G")
            with patch("partyline.resource_budget.host_resources", return_value=Host(4, 8 * GIB)):
                self.assertEqual(memory_ceiling(), 6 * GIB)
                self.assertEqual(self.file("16G").status_code, 400)

    def test_captain_can_deny_a_request(self):
        self.assertEqual(self.file("7G").status_code, 200)
        pending = self.client.get("/api/conversations/line/memory-request").json()["request"]
        self.actor = Principal(kind="machine", name="captain", conv_id="line",
                               attachment_id="captain", is_lead=True)
        self.assertEqual(self.client.delete(f"/api/memory-requests/{pending['id']}").status_code, 200)
        self.assertIsNone(self.client.get("/api/conversations/line/memory-request").json()["request"])

    def test_requester_cannot_approve_own_request_and_host_ceiling_is_refused(self):
        self.assertEqual(self.file("9G").status_code, 400)
        pending = self.file().json()
        self.assertEqual(self.client.post(f"/api/memory-requests/{pending['id']}/approve").status_code, 403)
        self.assertEqual(self.client.delete(f"/api/memory-requests/{pending['id']}").status_code, 403)

    def test_non_captain_worker_cannot_approve(self):
        self.assertEqual(self.file().status_code, 200)
        pending = self.client.get("/api/conversations/line/memory-request").json()["request"]
        self.db.add_attachment("worker2", "line", "worker2", "fake", ["fake"], self.temp.name)
        self.actor = Principal(kind="machine", name="worker2", conv_id="line",
                               attachment_id="worker2")
        response = self.client.post(f"/api/memory-requests/{pending['id']}/approve")
        self.assertEqual(response.status_code, 403)

    def test_subject_cannot_approve_raise_filed_by_parent_captain(self):
        self.actor = Principal(kind="user", name="person", user_id=1)
        response = self.client.post("/api/attachments/captain/memory-requests", json={
            "requested_limit": "5G", "reason": "larger process",
        })
        self.assertEqual(response.status_code, 200, response.text)
        request_id = response.json()["id"]
        self.actor = Principal(kind="machine", name="captain", conv_id="line",
                               attachment_id="captain", is_lead=True)
        denied = self.client.post(f"/api/memory-requests/{request_id}/approve")
        self.assertEqual(denied.status_code, 403)

    def test_live_full_budget_approval_releases_lease_and_grandfathers_replacement(self):
        from partyline.process_memory import parse_size
        from partyline.resource_budget import GIB

        self.db.add_attachment("occupier", "line", "occupier", "fake", ["fake"], self.temp.name)
        self.db._exec(
            "UPDATE attachments SET status='running',memory_limit='1G' "
            "WHERE id IN ('worker','captain','occupier')"
        )
        self.db.set_setting("max_live_processes", "4")
        self.db.set_setting("memory_reserve_bytes", str(1 * GIB))
        host = Host(cpus=4, ram_bytes=2 * GIB)
        self.runtime.live["worker"] = SimpleNamespace(att={"runtime_owner": "owner"})
        self.runtime.live["captain"] = SimpleNamespace(att={"runtime_owner": "captain-owner"})
        self.runtime.live["occupier"] = SimpleNamespace(att={"runtime_owner": "occupier-owner"})
        self.assertIsNotNone(refusal(self.db, GIB, host=host))
        self.assertEqual(self.file("5G").status_code, 200)
        pending = self.client.get("/api/conversations/line/memory-request").json()["request"]
        self.actor = Principal(kind="machine", name="captain", conv_id="line",
                               attachment_id="captain", is_lead=True)

        async def detach(_runtime, ident, **_kw):
            self.runtime.live.pop(ident, None)
            self.db._exec("UPDATE attachments SET status='stopped' WHERE id=?", (ident,))
            return {"ok": True}

        async def resume_with_budget(ident, _pending=None):
            row = self.db.get_attachment(ident)
            with patch("partyline.resource_budget.host_resources", return_value=host):
                accepted = await claim_resume(
                    self.db, ident, "replacement", parse_size(row["memory_limit"]),
                    grandfathered=ident in self.runtime.reattaching,
                )
            self.resumed.append((ident, ident in self.runtime.reattaching, accepted))

        async def resume_flow(_runtime, ident, _resume):
            await resume_with_budget(ident)

        self.runtime.reattaching.clear()
        with patch("partyline.line_process_routes.detach_attachment", side_effect=detach):
            with patch("partyline.memory_requests.resume_with_backlog", side_effect=resume_flow):
                response = self.client.post(f"/api/memory-requests/{pending['id']}/approve")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.resumed, [("worker", True, True)])

    def test_resume_failure_keeps_request_and_reports_recovery_path(self):
        self.assertEqual(self.file().status_code, 200)
        pending = self.client.get("/api/conversations/line/memory-request").json()["request"]
        self.actor = Principal(kind="machine", name="captain", conv_id="line",
                               attachment_id="captain", is_lead=True)
        with patch("partyline.memory_requests.resume_with_backlog", side_effect=RuntimeError("failed")):
            response = self.client.post(f"/api/memory-requests/{pending['id']}/approve")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["resume_failed"])
        still_pending = self.client.get("/api/conversations/line/memory-request").json()["request"]
        self.assertEqual(still_pending["id"], pending["id"])
