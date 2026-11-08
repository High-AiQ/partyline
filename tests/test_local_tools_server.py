"""Server-side local tools: the hub wired to the real helper session over a pipe, routes, MCP tools."""
import asyncio
import contextlib
import io
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from partyline import auth_store, auth_tokens, local_tools_audit
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.local_tools import TOO_OLD, GRACE, LocalTools, ToolLimits
from partyline.mcp import tools_blender
from partyline.mcp.client import ApiError
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime
from partyline.screen_routes import register_screen_routes
from partyline_helper import tools as helper_tools
from partyline_helper.client import Session
from partyline_helper.tools_audit import ToolAudit
from tests.screen_helper_fakes import FakeDesktop, FakeInputs, FakeTerminal
from tests.test_local_tools_helper import FakeAddon
from tests.test_screen_control_server import Pipe, SmallStepTime, until

REQUEST = "/api/conversations/line/local-tools/request"
CALL = "/api/conversations/line/local-tools/call"


class FlowCase(unittest.IsolatedAsyncioTestCase):
    """A real hub and a real helper session over an in-memory pipe, with a fake add-on."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.tmp.name}/test.db")
        self.db.create_conversation("line", "Line")
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        self.store = MediaStore(self.db, Path(self.tmp.name) / "media")
        self.hub = register_screen_routes(app, self.runtime, self.store)
        self.server_time = SmallStepTime()
        self.hub.tools.sleep = self.server_time.sleep
        self.user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("password1"))
        token = auth_tokens.create_access_token(auth_tokens.signing_secret(self.db), self.user["id"])
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver",
                                  headers={"Authorization": f"Bearer {token}"})
        self.device_id = self.hub.claim_pair_code(self.hub.issue_pair_code(self.user["id"], "line"),
                                                  "desk", "test")[0]
        self.tasks = []
        self.out = io.StringIO()
        self.stdout = contextlib.redirect_stdout(self.out)
        self.stdout.__enter__()

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with contextlib.suppress(BaseException):
                await task
        self.stdout.__exit__(None, None, None)
        await self.client.aclose()
        self.db.close()
        self.tmp.cleanup()

    async def connect(self):
        self.pipe = Pipe()
        self.desktop, self.terminal = FakeDesktop(), FakeTerminal()
        self.terminal.box_answer = (True, False)
        self.clock = SmallStepTime()
        self.session = Session(self.pipe.helper, self.desktop, self.terminal, "desk", clock=self.clock,
                               sleep=self.clock.sleep, inputs=FakeInputs(self.desktop))
        self.addon = FakeAddon()
        self.session.tools.addon_for = lambda spec: self.addon
        self.session.tools.audit = ToolAudit(Path(self.tmp.name) / "helper-audit.jsonl", clock=self.clock)
        row = dict(self.db._exec("SELECT * FROM screen_devices WHERE id=?", (self.device_id,)).fetchone())
        self.tasks += [asyncio.create_task(self.hub.connect(self.pipe.server, row)),
                       asyncio.create_task(self.session.run())]
        await until(lambda: self.device_id in self.hub.devices)

    def item(self):
        return self.hub.tools.sessions.get("line")

    async def grant(self, **body):
        response = await self.client.post(REQUEST, json={"tool": "blender", **body})
        self.assertEqual(response.status_code, 200, response.text)
        await until(lambda: self.item() and self.item().status == "active")

    async def run_code(self, code="print(1)", timeout_s=5):
        body = {"op": "exec", "args": {"code": code}, "timeout_s": timeout_s}
        return await self.client.post(CALL, json=body)

    def bodies(self):
        return [row["body"] for row in self.db.list_messages("line")]


class ToolsFlowTest(FlowCase):
    async def test_request_grant_exec_audit_and_end(self):
        await self.connect()
        self.assertEqual(self.hub.devices[self.device_id]["tools"], 1)
        self.assertEqual((await self.client.get("/api/conversations/line/local-tools")).json(),
                         {"session": None})
        early = await self.run_code()
        self.assertEqual(early.status_code, 409)
        self.assertIn("not granted", early.json()["detail"])
        await self.grant(checker=True)
        self.terminal.box_answer = (True, True)
        view = (await self.client.get("/api/conversations/line/local-tools")).json()["session"]
        self.assertEqual((view["status"], view["tool"]), ("active", "blender"))
        self.assertEqual(view["info"]["file"], "scene.blend")
        answer = await self.run_code("print('hi')\n" * 3)
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()["stdout"], "hi\n")
        again = await self.client.post(REQUEST, json={"tool": "blender"})
        self.assertIn("already active", again.json()["message"])
        ended = await self.client.post("/api/conversations/line/local-tools/end")
        self.assertEqual(ended.json(), {"status": "ended"})
        await until(lambda: self.addon.closed)
        self.assertIsNone(self.session.tools.grant)
        rows = local_tools_audit.rows(self.db, self.addon.opened[0][0])
        self.assertEqual([r["kind"] for r in rows], ["event", "call", "result", "event"])
        self.assertIn("print('hi')", rows[1]["code"])
        for earlier, later in zip(rows, rows[1:], strict=False):
            self.assertEqual(later["previous_hash"], earlier["entry_hash"])
        self.assertTrue(any("Local tools audit" in body and "audit sha256" in body for body in self.bodies()))
        self.assertEqual((await self.run_code()).status_code, 409)

    async def test_decline_means_no_session(self):
        await self.connect()
        self.terminal.box_answer = (False, False)
        await self.client.post(REQUEST, json={"tool": "blender"})
        await until(lambda: self.item() is None)
        self.assertTrue(any("were not granted" in body for body in self.bodies()))
        self.assertEqual(self.addon.opened, [])

    async def test_silence_timeout_declines_like_no(self):
        await self.connect()
        self.terminal.box_answer = asyncio.get_running_loop().create_future()
        await self.client.post(REQUEST, json={"tool": "blender"})
        await until(lambda: self.terminal.asks.qsize())
        self.terminal.box_answer.set_result((False, False))  # ask_box returns this on timeout
        await until(lambda: self.item() is None)
        self.assertEqual(self.addon.opened, [])

    async def test_person_revokes_in_partyline_and_the_helper_ends_it(self):
        await self.connect()
        await self.grant()
        session_id = self.item().session_id
        other = await self.client.delete("/api/local-tools/sessions/nope")
        self.assertEqual(other.status_code, 404)
        url = f"/api/local-tools/sessions/{session_id}"
        self.assertEqual((await self.client.delete(url)).status_code, 200)
        await until(lambda: self.session.tools.grant is None)
        self.assertEqual(self.addon.closed, [session_id])
        self.assertEqual(self.item().status, "revoked")
        self.assertEqual((await self.client.delete(url)).status_code, 409)
        refused = await self.run_code()
        self.assertIn("revoked by person", refused.json()["detail"])

    async def test_local_kill_reaches_the_server_and_blocks_calls(self):
        await self.connect()
        await self.grant()
        self.session.status.request_stop_tools()
        await until(lambda: self.item().status == "revoked")
        self.assertIn("tray", self.item().reason)
        self.assertTrue(any("tools revoked" in body for body in self.bodies()))
        again = await self.client.post(REQUEST, json={"tool": "blender"})  # a new session, but cooling down
        self.assertEqual(again.status_code, 200)
        await until(lambda: any("may ask again" in body for body in self.bodies()))
        self.assertEqual(self.addon.opened[1:], [])

    async def test_disconnect_and_restart_end_the_grant(self):
        await self.connect()
        await self.grant()
        self.pipe.cut()
        await until(lambda: self.item().status == "revoked")
        self.assertIn("disconnected", self.item().reason)
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.assertIsNone(self.session.tools.grant)
        fresh = LocalTools(self.hub)  # a server restart: nothing survives in memory
        self.assertIsNone(fresh.view("line"))

    async def test_runaway_call_gets_cancel_after_timeout_plus_grace(self):
        await self.connect()
        await self.grant()
        self.addon.release = asyncio.get_running_loop().create_future()
        waits = []

        def deadline(delay):
            waits.append((delay, asyncio.timeout(None)))
            return waits[-1][1]
        self.hub.tools.deadline = deadline
        call = asyncio.create_task(self.run_code("while True: pass", timeout_s=1))
        await until(lambda: self.addon.calls)
        self.assertEqual(waits[0][0], 1 + GRACE)  # the server waits the call's timeout plus a grace
        waits[0][1].reschedule(asyncio.get_running_loop().time())  # that time passes
        response = await call
        self.assertEqual(response.status_code, 409)
        self.assertIn("did not answer in time", response.json()["detail"])
        await until(lambda: self.addon.cancelled)

    async def test_rate_and_session_limits(self):
        await self.connect()
        await self.grant()
        self.hub.tools.limits = ToolLimits(per_minute=2, per_session=3)
        codes = [(await self.run_code()).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 409])
        item = self.item()
        item.times.clear()
        self.assertEqual((await self.run_code()).status_code, 200)
        item.times.clear()
        refused = await self.run_code()
        self.assertIn("session cap", refused.json()["detail"])

    async def test_offline_old_helper_and_bad_requests(self):
        response = await self.client.post(REQUEST, json={"tool": "blender"})
        self.assertIn("no paired computer", response.json()["detail"])
        await self.connect()
        self.hub.devices[self.device_id]["tools"] = 0
        old = await self.client.post(REQUEST, json={"tool": "blender"})
        self.assertEqual(old.json()["detail"], TOO_OLD)
        self.hub.devices[self.device_id]["tools"] = 1
        for body in ({"tool": "Bad Name"}, {"tool": "blender", "extra": 1}):
            self.assertEqual((await self.client.post(REQUEST, json=body)).status_code, 422)
        slow = await self.client.post(CALL, json={"op": "exec", "timeout_s": 999})
        self.assertEqual(slow.status_code, 422)
        self.assertEqual((await self.client.post("/api/conversations/line/local-tools/end")).status_code, 409)
        await self.grant()
        big = await self.run_code("x" * 70000)
        self.assertIn("larger than", big.json()["detail"])
        pending = LocalTools(self.hub)
        self.assertEqual(pending.limits.per_minute, 60)
        with self.assertRaises(ValueError):
            await pending.request("line", "a", "Line", "../x")

    async def test_old_device_after_helper_refuses_other_holder(self):
        await self.connect()
        await self.grant()
        with self.assertRaisesRegex(ValueError, "held by person"):
            await self.hub.tools.request("line", "agent-b", "Line", "blender")
        with self.assertRaisesRegex(ValueError, "granted to person"):
            await self.hub.tools.call("line", "agent-b", "exec", {}, 5)
        with self.assertRaisesRegex(ValueError, "held by person"):
            await self.hub.tools.end("line", "agent-b")
        self.hub.devices.pop(self.device_id)
        with self.assertRaisesRegex(ValueError, "offline"):
            await self.hub.tools.call("line", "person", "exec", {}, 5)
        self.assertEqual(self.item().status, "revoked")

    async def test_render_checks_added_to_a_live_session(self):
        await self.connect()
        await self.grant()
        self.session.terminal.control_answer = True
        await self.client.post(REQUEST, json={"tool": "blender", "checker": True})
        await until(lambda: self.item().checker)
        self.assertTrue(any("now include render checks" in body for body in self.bodies()))
        self.assertIs(self.helper_grant()["checker"], True)

    async def test_a_local_kill_during_a_render_check_question_revokes_the_session(self):
        await self.connect()
        await self.grant()
        self.session.terminal.control_answer = asyncio.get_running_loop().create_future()
        await self.client.post(REQUEST, json={"tool": "blender", "checker": True})
        await until(lambda: self.item().scope_pending and self.session.tools.prompting)
        self.session.status.request_stop_tools()
        await until(lambda: self.item().status == "revoked")
        self.assertFalse(self.item().scope_pending)
        self.assertIsNone(self.session.tools.grant)
        refused = await self.run_code()
        self.assertEqual(refused.status_code, 409)  # not "granted": the person ended it
        again = await self.client.post(REQUEST, json={"tool": "blender"})
        self.assertNotIn("already active", again.text)
        await until(lambda: any("may ask again" in body for body in self.bodies()))
        self.session.tools.cooldown_until -= helper_tools.COOLDOWN  # the ten minutes pass
        self.terminal.box_answer = (True, False)
        await self.grant()
        self.assertEqual((await self.run_code()).status_code, 200)

    async def test_declining_only_the_render_checks_keeps_the_session(self):
        await self.connect()
        await self.grant()
        self.session.terminal.control_answer = False
        await self.client.post(REQUEST, json={"tool": "blender", "checker": True})
        await until(lambda: any("Render checks were not granted" in body for body in self.bodies()))
        self.assertEqual(self.item().status, "active")
        self.assertFalse(self.item().scope_pending)
        self.assertEqual((await self.run_code()).status_code, 200)

    def helper_grant(self):
        return self.session.tools.grant


class ToolsLimitsAndMcpTest(unittest.TestCase):
    def test_limits_from_env(self):
        self.assertEqual(ToolLimits.from_env({"PARTYLINE_TOOLS_RATE": "5"}).per_minute, 5)
        self.assertEqual(ToolLimits.from_env({}).per_session, 500)
        with self.assertRaises(ValueError):
            ToolLimits.from_env({"PARTYLINE_TOOLS_RATE": "0"})
        self.assertEqual(ToolLimits.from_env({}).render_checks, 200)
        self.assertEqual(ToolLimits.from_env({"PARTYLINE_RENDER_CHECK_MAX": "7"}).render_checks, 7)
        with self.assertRaises(ValueError):
            ToolLimits.from_env({"PARTYLINE_RENDER_CHECK_MAX": "many"})

    def test_audit_recover_publishes_pending_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Db(f"{tmp}/t.db")
            db.create_conversation("line", "Line")
            local_tools_audit.record(db, "s", "line", "agent", "call", "exec", "exec 3 bytes", "abc")
            local_tools_audit.recover(db)
            self.assertIsNone(local_tools_audit.publish(db, "s"))
            self.assertIn("Local tools audit", db.list_messages("line")[-1]["body"])
            self.assertEqual(local_tools_audit.first_line("\n  import bpy  \nx" + "y" * 80, 10), "import bpy")
            db.close()

    def test_tools_gate_validate_and_route(self):
        self.assertEqual(tools_blender.tool_list({"actions": ["read"]}), [])
        names = [t["name"] for t in tools_blender.tool_list({"actions": ["write"]})]
        self.assertEqual(names, ["blender_request", "blender_exec", "blender_scene_info", "blender_render",
                                 "blender_screenshot", "blender_end"])
        calls = []
        client = SimpleNamespace(home="line/1", request=lambda *a, **k: calls.append((a, k)) or {"ok": 1})
        state = {"actions": ["write"]}
        base = "/api/conversations/line%2F1/local-tools"
        tools_blender.call(client, "blender_request", {"checker": True}, state)
        tools_blender.call(client, "blender_exec", {"code": "1", "timeout_s": 60}, state)
        tools_blender.call(client, "blender_scene_info", {"detail": "object", "name": "Cube"}, state)
        projection = {"detail": "object", "project_to_camera": True, "camera": "Side", "margin": 0.05,
                      "supports": {"Lamp": "Table"}}
        tools_blender.call(client, "blender_end", {}, state)
        tools_blender.call(client, "blender_scene_info", projection, state)
        tools_blender.call(client, "blender_render",
                           {"camera": "Side", "width": 640, "engine": "eevee"}, state)
        tools_blender.call(client, "blender_render", {"timeout_s": 90}, state)
        tools_blender.call(client, "blender_screenshot", {"max_size": 800}, state)
        self.assertEqual(calls[5:], [
            (("POST", base + "/call", {"op": "render", "timeout_s": 60,
                                       "args": {"camera": "Side", "width": 640, "engine": "eevee"}}),
             {"timeout": 75}),
            (("POST", base + "/call", {"op": "render", "timeout_s": 90, "args": {}}), {"timeout": 105}),
            (("POST", base + "/call", {"op": "screenshot", "timeout_s": 20, "args": {"max_size": 800}}),
             {"timeout": 35})])
        self.assertEqual(calls[4], (("POST", base + "/call", {"op": "scene_info", "args": projection}),
                                    {"timeout": 35}))
        self.assertEqual(calls[:4], [
            (("POST", base + "/request", {"tool": "blender", "checker": True}), {}),
            (("POST", base + "/call", {"op": "exec", "args": {"code": "1"}, "timeout_s": 60}),
             {"timeout": 75}),
            (("POST", base + "/call", {"op": "scene_info", "args": {"detail": "object", "name": "Cube"}}),
             {"timeout": 35}),
            (("POST", base + "/end"), {})])
        for name, args in (("blender_render", {"engine": "cycles"}), ("blender_render", {"width": "big"}),
                           ("blender_render", {"timeout_s": 500}), ("blender_screenshot", {"max_size": 0}),
                           ("blender_render", {"extra": 1}), ("blender_exec", {"code": ""}),
                           ("blender_exec", {"code": "1", "timeout_s": 500}),
                           ("blender_scene_info", {"detail": "all"}), ("blender_end", {"x": 1})):
            with self.assertRaises(ValueError):
                tools_blender.call(client, name, args, state)
        with self.assertRaises(ApiError):
            tools_blender.call(client, "blender_end", {}, {"actions": ["read"]})
