"""Approved raises reach the running scope; create_task honors memory ceilings."""

from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from partyline.auth_guard import Principal
from partyline.process_memory import backstop_bytes, parse_size
from partyline.orchestrator_contracts import TaskIn
from partyline.orchestrator_service import create_task
from tests.orchestrator_fixture import TaskFixture
from tests.test_memory_requests import MemoryRequestTest

UNIT = "partyline-process-" + "a" * 32 + ".scope"


class LiveRaiseTest(MemoryRequestTest):
    def approve(self):
        self.assertEqual(self.file().status_code, 200)
        pending = self.client.get("/api/conversations/line/memory-request").json()["request"]
        self.actor = Principal(kind="machine", name="captain", conv_id="line",
                               attachment_id="captain", is_lead=True)
        self.adapter = SimpleNamespace(att=self.db.get_attachment("worker"), memory_scope=UNIT,
                                       memory_limit="3G")
        self.runtime.live["worker"] = self.adapter
        self.detached = []

        async def detach(_runtime, ident, **_kw):
            self.detached.append(ident)
            self.runtime.live.pop(ident, None)

        self.calls = []

        def run(argv, **_kw):
            self.calls.append(argv)
            return SimpleNamespace(returncode=self.rc, stdout="", stderr="")

        with patch("partyline.line_process_routes.detach_attachment", side_effect=detach), \
                patch("partyline.memory_live_raise.subprocess.run", side_effect=run), \
                patch("partyline.memory_live_raise.read_scope_memory_max",
                      return_value=self.readback):
            return self.client.post(f"/api/memory-requests/{pending['id']}/approve")

    def test_live_raise_succeeds_without_restart(self):
        self.rc, self.readback = 0, str(backstop_bytes(parse_size("5G")))
        response = self.approve()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.detached, [])
        self.assertEqual(self.resumed, [])
        self.assertEqual(self.db.get_attachment("worker")["memory_limit"], "5G")
        self.assertEqual(self.adapter.memory_limit, "5G")
        self.assertIn(f"MemoryMax={self.readback}", self.calls[0])
        self.assertIn("MemorySwapMax=0", self.calls[0])
        self.assertIn(UNIT, self.calls[0])
        self.assertIn("applied to the running process", self.notice())

    def notice(self):
        return " ".join(m["body"] for m in self.db.message_page("line", limit=50)[0])

    def test_full_budget_refuses_with_409_and_leaves_process_running(self):
        self.rc, self.readback = 0, str(backstop_bytes(parse_size("5G")))
        with patch("partyline.memory_live_raise.reject_if_full",
                   side_effect=HTTPException(409, "budget full")):
            response = self.approve()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.detached, [])
        self.assertEqual(self.resumed, [])
        self.assertIn("worker", self.runtime.live)
        self.assertNotEqual(self.db.get_attachment("worker")["memory_limit"], "5G")

    def test_set_property_failure_falls_back_to_detach_and_resume(self):
        self.rc, self.readback = 1, None
        self.assertEqual(self.approve().status_code, 200)
        self.assertEqual(self.detached, ["worker"])
        self.assertEqual(self.resumed, [("worker", True)])
        self.assertEqual(self.db.get_attachment("worker")["memory_limit"], "5G")
        self.assertIn("process restarted", self.notice())

    def test_readback_mismatch_falls_back(self):
        self.rc, self.readback = 0, str(parse_size("4G"))
        self.assertEqual(self.approve().status_code, 200)
        self.assertEqual(self.detached, ["worker"])
        self.assertEqual(self.resumed, [("worker", True)])

    def test_unknown_unit_falls_back(self):
        self.rc, self.readback = 0, "1"
        self.runtime.live.clear()
        self.assertEqual(self.file().status_code, 200)
        pending = self.client.get("/api/conversations/line/memory-request").json()["request"]
        self.actor = Principal(kind="machine", name="captain", conv_id="line",
                               attachment_id="captain", is_lead=True)
        self.runtime.live["worker"] = SimpleNamespace(att={}, memory_scope=None)

        async def detach(_runtime, ident, **_kw):
            self.runtime.live.pop(ident, None)

        with patch("partyline.line_process_routes.detach_attachment", side_effect=detach):
            self.assertEqual(
                self.client.post(f"/api/memory-requests/{pending['id']}/approve").status_code, 200)
        self.assertEqual(self.resumed, [("worker", True)])


class TaskMemoryLimitTest(TaskFixture):
    def setUp(self):
        super().setUp()
        patcher = patch("partyline.memory_live_raise.memory_ceiling", return_value=8 * 1024**3)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db.set_setting("memory_captain_ceiling_bytes", str(6 * 1024**3))

    def make(self, limit, actor, name="heavy"):
        return create_task(self.runtime, actor, "root", TaskIn(
            name=name, goal="Render", implementer="builder", review="inspector",
            memory_limit=limit))

    async def test_within_captain_ceiling_is_applied(self):
        row = await self.make("6G", self.captain)
        self.assertEqual(self.db.get_attachment(row["implementer_id"])["memory_limit"], "6G")

    async def test_above_captain_ceiling_is_403_and_creates_nothing(self):
        with self.assertRaises(HTTPException) as caught:
            await self.make("7G", self.captain)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertIn("memory request", caught.exception.detail)
        self.assertEqual(self.db._exec("SELECT 1 FROM task_reviews").fetchall(), [])

    async def test_person_may_exceed_captain_ceiling_but_not_host(self):
        row = await self.make("7G", self.human)
        self.assertEqual(self.db.get_attachment(row["implementer_id"])["memory_limit"], "7G")
        with self.assertRaises(HTTPException) as caught:
            await self.make("9G", self.human, "huge")
        self.assertEqual(caught.exception.status_code, 400)
