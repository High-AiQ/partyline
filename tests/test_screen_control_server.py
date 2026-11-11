"""Server-side agent control: an in-process hub wired to the real helper session over a pipe."""
import asyncio
import contextlib
import io
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, WebSocketDisconnect
from httpx import ASGITransport, AsyncClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.mcp import tools_control
from partyline.mcp.client import ApiError
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime
from partyline.screen_control import TOO_OLD, ControlHub, ControlLimits, Grant
from partyline.screen_control_actions import ControlAction, command, to_os
from partyline.screen_frames import BufferedFrame, ShareBuffer
from partyline.screen_routes import pointer_coordinates, register_screen_routes
from partyline_helper import acting
from partyline_helper.client import Session
from tests.screen_helper_fakes import (
    REGION, FakeDesktop, FakeInputs, FakeTerminal, ManualTime, checkpoint,
)

CLOSED = object()


class SmallStepTime(ManualTime):
    """Sub-second sleeps (watcher, settle, drag) pass at once; heartbeats wait for advance()."""

    async def sleep(self, delay):
        if delay >= 1:
            return await super().sleep(delay)
        self.now = round(self.now + max(0, delay), 9)
        await checkpoint()


class Pipe:
    """An in-memory WebSocket: the hub sees Starlette's API, the helper sees websockets'."""

    def __init__(self):
        self.up, self.down = asyncio.Queue(), asyncio.Queue()
        self.server, self.helper = ServerEnd(self), HelperEnd(self)

    def cut(self):
        self.up.put_nowait(CLOSED)
        self.down.put_nowait(CLOSED)


class ServerEnd:
    def __init__(self, pipe):
        self.pipe = pipe

    async def accept(self):
        pass

    async def receive_text(self):
        item = await self.pipe.up.get()
        if item is CLOSED:
            raise WebSocketDisconnect(1006)
        return item

    receive_bytes = receive_text

    async def send_json(self, data):
        self.pipe.down.put_nowait(json.dumps(data))

    async def close(self, code=1000, reason=""):
        self.pipe.down.put_nowait(CLOSED)


class HelperEnd:
    close_code = 1000

    def __init__(self, pipe):
        self.pipe = pipe

    async def send(self, value):
        self.pipe.up.put_nowait(value)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.pipe.down.get()
        if item is CLOSED:
            raise StopAsyncIteration
        return item

    async def close(self, code=1000, reason=""):
        self.pipe.up.put_nowait(CLOSED)


async def until(condition, limit=10_000):
    for _ in range(limit):
        if condition():
            return
        await checkpoint()
    raise AssertionError("condition never became true")


class ControlFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.tmp.name}/test.db")
        self.db.create_conversation("line", "Line")
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        self.hub = register_screen_routes(app, self.runtime,
                                          MediaStore(self.db, Path(self.tmp.name) / "media"))
        self.audit_time = ManualTime()
        self.hub.control.sleep = self.audit_time.sleep
        self.user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("password1"))
        token = auth_tokens.create_access_token(auth_tokens.signing_secret(self.db), self.user["id"])
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver",
                                  headers={"Authorization": f"Bearer {token}"})
        code = self.hub.issue_pair_code(self.user["id"], "line")
        self.device_id = self.hub.claim_pair_code(code, "desk", "test")[0]
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
        self.inputs, self.clock = FakeInputs(self.desktop), SmallStepTime()
        self.session = Session(self.pipe.helper, self.desktop, self.terminal, "desk",
                               clock=self.clock, sleep=self.clock.sleep, inputs=self.inputs)
        row = dict(self.db._exec("SELECT * FROM screen_devices WHERE id=?", (self.device_id,)).fetchone())
        self.tasks += [asyncio.create_task(self.hub.connect(self.pipe.server, row)),
                       asyncio.create_task(self.session.run())]
        await until(lambda: self.device_id in self.hub.devices)

    async def share(self, **extra):
        response = await self.client.post("/api/screen/shares?conv_id=line", json={
            "device_id": self.device_id, "region": REGION, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        await until(lambda: self.hub.shares.get("line") and self.hub.shares["line"].status == "active"
                    and self.hub.shares["line"].frames)
        return self.hub.shares["line"]

    def grant(self):
        share = self.hub.shares.get("line")
        return self.hub.control.grants.get(share.share_id) if share else None

    def bodies(self):
        return [row["body"] for row in self.db.list_messages("line")]

    async def act(self, **action):
        return await self.client.post("/api/conversations/line/screen-control/action", json=action)

    async def test_request_grant_act_audit_kill_switch(self):
        await self.connect()
        self.assertEqual(self.hub.devices[self.device_id]["control"], 1)
        share = await self.share()
        refused = await self.act(kind="click", x=1, y=1)
        self.assertIn("call screen_control_request first", refused.json()["detail"])
        self.terminal.control_answer = True
        response = await self.client.post("/api/conversations/line/screen-control/request")
        self.assertEqual(response.json()["status"], "pending", response.text)
        await until(lambda: self.grant().status == "active")
        granted = "@person Agent control of desk granted"
        self.assertTrue(any(body.startswith(granted) for body in self.bodies()))
        again = await self.client.post("/api/conversations/line/screen-control/request")
        self.assertEqual(again.json()["status"], "granted")
        current = await self.client.get("/api/screen/shares?conv_id=line")
        self.assertEqual(current.json()["share"]["control"]["status"], "active")
        frame = share.frames[-1]
        self.assertEqual((frame.out_width, frame.out_height), (200, 100))
        response = await self.act(kind="click", x=10, y=20)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["done"], "click left (-90,20)")
        self.assertIn("/api/media/", response.json()["frame"])
        self.assertIn(("click", "left", 1), self.inputs.calls)
        self.assertEqual(share.frames[-1].pointer, {"x": -90, "y": 20, "visible": True})
        for _ in range(3):
            self.assertEqual((await self.act(kind="move", x=50, y=50)).status_code, 200)
        self.assertEqual((await self.act(kind="type", text="hi `there`")).status_code, 200)
        for action, detail in ((dict(kind="click", x=200, y=0), "outside the shared region"),
                               (dict(kind="type", text="x" * 501), "500 characters"),
                               (dict(kind="key", keys="ctrl+alt+del"), "blocked for agents"),
                               (dict(kind="scroll", x=1, y=1), "not both 0")):
            refused = await self.act(**action)
            self.assertEqual(refused.status_code, 409)
            self.assertIn(detail, refused.json()["detail"])
        self.assertEqual((await self.act(kind="click", x="1", y=1)).status_code, 422)
        self.assertFalse(any("audit" in body for body in self.bodies()))
        self.audit_time.advance(60)
        await until(lambda: any("audit" in body for body in self.bodies()))
        audit = next(body for body in self.bodies() if "audit" in body)
        self.assertTrue(audit.startswith(
            "Agent control audit — person: click left (-90,20) · move (-50,50) ×3 · "
            "type `hi 'there'` (10 chars)"))
        self.desktop.position = (90, 90)  # the person grabs the mouse
        self.inputs.on_move()
        await until(lambda: self.grant().status == "revoked")
        self.assertTrue(any(body.startswith("@person Agent control revoked (the pointer was moved")
                            for body in self.bodies()))
        refused = await self.act(kind="move", x=1, y=1)
        self.assertIn("revoked", refused.json()["detail"])
        again = await self.client.post("/api/conversations/line/screen-control/request")
        self.assertIn("start a new share", again.json()["detail"])
        await self.client.delete(f"/api/screen/shares/{share.share_id}")
        self.assertEqual(self.hub.control.grants, {})

    async def test_frame_choices_and_deduplication(self):
        await self.connect()
        await self.share()
        self.terminal.control_answer = True
        await self.client.post("/api/conversations/line/screen-control/request")
        await until(lambda: self.grant().status == "active")
        baseline = len(self.bodies())
        media_baseline = self.db._exec("SELECT count(*) FROM images").fetchone()[0]
        first = await self.act(kind="click", x=10, y=20)
        self.assertEqual(first.status_code, 200, first.text)
        url = first.json()["frame"]
        self.assertTrue(url.endswith("/thumb"))
        self.assertEqual(len(self.bodies()), baseline)
        self.assertEqual(self.db._exec("SELECT count(*) FROM images").fetchone()[0],
                         media_baseline + 1)
        again = await self.act(kind="move", x=11, y=20, frame="full")
        self.assertTrue(again.json()["unchanged"])
        self.assertEqual(again.json()["frame"], url.removesuffix("thumb") + "original")
        self.assertEqual(self.db._exec("SELECT count(*) FROM images").fetchone()[0],
                         media_baseline + 1)
        none = await self.act(kind="move", x=12, y=20, frame="none")
        self.assertEqual(set(none.json()), {"done"})
        self.desktop.image.putpixel((0, 0), (0, 0, 0))
        capture = self.desktop.capture_sessions[-1]
        frames_before_change = len(self.hub.shares["line"].frames)
        self.clock.advance(.21)  # The share's default rate cap is 5 fps.
        capture.on_frame(self.desktop.image.copy(), (REGION["x"], REGION["y"]))
        await until(lambda: len(self.hub.shares["line"].frames) > frames_before_change)
        changed = await self.act(kind="move", x=13, y=20)
        self.assertNotIn("unchanged", changed.json())
        self.assertNotEqual(changed.json()["frame"], url)
        self.assertEqual(self.db._exec("SELECT count(*) FROM images").fetchone()[0],
                         media_baseline + 2)
        invalid = await self.act(kind="move", x=13, y=20, frame="large")
        self.assertEqual(invalid.status_code, 422)

    async def test_each_action_publishes_the_new_count_to_the_line(self):
        await self.connect()
        await self.share()
        events = []
        send = self.hub._line_event

        async def record(conv_id, payload):
            events.append(payload)
            await send(conv_id, payload)

        self.hub._line_event = record
        self.terminal.control_answer = True
        await self.client.post("/api/conversations/line/screen-control/request")
        await until(lambda: self.grant().status == "active")
        events.clear()
        for _ in range(3):
            self.assertEqual((await self.act(kind="move", x=50, y=50)).status_code, 200)
        controls = [event["share"]["control"] for event in events if event["type"] == "screen_share"]
        self.assertEqual([(c["status"], c["actions"]) for c in controls],
                         [("active", 1), ("active", 2), ("active", 3)])

    async def test_share_start_control_ends_on_disconnect(self):
        await self.connect()
        self.terminal.control_answer = True
        share = await self.share(control=True)
        await until(lambda: self.grant() and self.grant().status == "active")
        self.assertIsNone(self.grant().holder)  # granted with the share: any agent on the line
        self.assertEqual((await self.act(kind="move", x=0, y=0)).status_code, 200)
        self.pipe.cut()
        await until(lambda: "line" not in self.hub.shares)
        await until(lambda: self.inputs.stopped)
        self.assertFalse(self.session.control.granted)
        self.assertIn("Agent control ended with the share (device disconnected).", self.bodies())
        self.assertIn("person: move (-100,0)", " ".join(self.bodies()))
        self.assertEqual(self.hub.control.grants, {})
        self.assertEqual(share.status, "stopped")

    async def test_revoke_and_stop_overtake_queued_actions(self):
        await self.connect()
        gate = asyncio.Event()
        sleep = self.session.sleep

        async def settle_waits_for_gate(delay):
            await (gate.wait() if delay == acting.SETTLE else sleep(delay))
        self.session.sleep = settle_waits_for_gate
        for stop in ("control", "share"):
            gate.clear()
            share = await self.share()
            self.terminal.control_answer = True
            await self.client.post("/api/conversations/line/screen-control/request")
            await until(lambda: self.grant() and self.grant().status == "active")
            first = asyncio.create_task(self.act(kind="move", x=10, y=10))
            second = asyncio.create_task(self.act(kind="move", x=20, y=20))
            await until(lambda: len(self.session.control.pending) == 1)  # first is in its settle
            url = f"/api/screen/shares/{share.share_id}" + ("/control" if stop == "control" else "")
            self.assertEqual((await self.client.delete(url)).status_code, 200)
            refused = await second
            self.assertEqual(refused.status_code, 409, stop)
            self.assertFalse(self.session.control.granted)
            gate.set()
            await first
            moves = [call for call in self.inputs.calls if call[0] == "move"]
            self.assertEqual(moves[-1], ("move", -90, 10), stop)  # the second move never ran
            self.assertNotIn(("move", -80, 20), moves)
            if stop == "control":
                await self.client.delete(f"/api/screen/shares/{share.share_id}")
            await until(lambda: "line" not in self.hub.shares)

    async def test_decline_and_person_revoke_route(self):
        await self.connect()
        share = await self.share()
        await self.client.post("/api/conversations/line/screen-control/request")
        await until(lambda: self.grant() is None)
        self.assertTrue(any("Agent control was not granted (Local consent declined" in body
                            for body in self.bodies()))
        url = f"/api/screen/shares/{share.share_id}/control"
        self.assertEqual((await self.client.delete(url)).status_code, 409)
        self.terminal.control_answer = asyncio.get_running_loop().create_future()
        await self.client.post("/api/conversations/line/screen-control/request")
        await until(lambda: self.session.control.prompting)
        self.assertEqual((await self.client.delete(url)).status_code, 200)  # withdrawn while asking
        await until(lambda: not self.session.control.prompting)
        withdrawn = "@person Agent control request withdrawn"
        self.assertTrue(any(body.startswith(withdrawn) for body in self.bodies()))
        self.assertIn("start a new share",
                      (await self.client.post("/api/conversations/line/screen-control/request")).text)
        await self.client.delete(f"/api/screen/shares/{share.share_id}")
        share = await self.share()
        url = f"/api/screen/shares/{share.share_id}/control"
        self.terminal.control_answer = True
        await self.client.post("/api/conversations/line/screen-control/request")
        await until(lambda: self.grant() and self.grant().status == "active")
        self.assertEqual((await self.client.delete(url)).status_code, 200)
        await until(lambda: not self.session.control.granted)
        self.assertIn("revoked from Partyline", self.session.control.revoked)
        self.assertEqual((await self.client.delete("/api/screen/shares/nope/control")).status_code, 404)


class ControlUnitTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.tmp.name}/test.db")
        self.db.create_conversation("line", "Line")
        self.runtime = ChatRuntime(self.db)
        self.hub = register_screen_routes(FastAPI(), self.runtime,
                                          MediaStore(self.db, Path(self.tmp.name) / "media"))
        self.share = ShareBuffer("share", "line", "device", 1, "person", dict(REGION), status="active")
        self.share.add(BufferedFrame(b"x", 1, dict(REGION), 100, 50, None, "image/png"))
        self.hub.shares["line"] = self.share
        self.sent = []

        class Socket:
            async def send_json(inner, message):
                self.sent.append(message)

        self.device = {"id": "device", "name": "desk", "os": "Windows", "socket": Socket(),
                       "monitors": [], "control": 1}
        self.hub.devices["device"] = self.device

    async def asyncTearDown(self):
        self.db.close()
        self.tmp.cleanup()

    async def test_old_helpers_get_a_clear_error(self):
        self.device.pop("control")
        with self.assertRaisesRegex(ValueError, "helper too old for control"):
            await self.hub.control.request("line", "agent-a", "Line")
        self.assertIn("helper too old", TOO_OLD)
        self.assertEqual(self.sent, [])

    async def test_refusals_and_holder_binding(self):
        self.hub.walkthroughs.items["share"] = object()
        with self.assertRaisesRegex(ValueError, "Show me"):
            await self.hub.control.request("line", "agent-a", "Line")
        del self.hub.walkthroughs.items["share"]
        self.hub.devices.pop("device")
        with self.assertRaisesRegex(ValueError, "offline"):
            await self.hub.control.request("line", "agent-a", "Line")
        self.hub.devices["device"] = self.device
        self.assertEqual((await self.hub.control.request("line", "agent-a", "Line"))["status"], "pending")
        self.assertEqual(self.sent[-1], {"type": "control_request", "share_id": "share",
                                         "requested_by": "agent-a", "line_name": "Line"})
        with self.assertRaisesRegex(ValueError, "already waiting"):
            await self.hub.control.request("line", "agent-b", "Line")
        await self.hub.control.from_helper(self.device, {"type": "control_granted", "share_id": "share"})
        with self.assertRaisesRegex(ValueError, "held by agent-a"):
            await self.hub.control.request("line", "agent-b", "Line")
        with self.assertRaisesRegex(ValueError, "granted to agent-a"):
            await self.hub.control.action("line", "agent-b", ControlAction(kind="move", x=1, y=1))
        with self.assertRaisesRegex(ValueError, "meta\\+l is blocked"):  # Windows lock, from hello's OS
            await self.hub.control.action("line", "agent-a", ControlAction(kind="key", keys="Win+L"))
        self.hub.shares.pop("line")
        with self.assertRaisesRegex(ValueError, "nobody is sharing"):
            await self.hub.control.action("line", "agent-a", ControlAction(kind="move", x=1, y=1))

    async def test_action_timeouts_refusals_and_stale_frames(self):
        control = self.hub.control
        control.grants["share"] = Grant("share", "agent-a", "agent-a", status="active")

        async def answer(ok=True, frame=True, started=False):
            await until(lambda: control.waiters)
            request_id = next(iter(control.waiters))
            await control.from_helper({"id": "other"}, {"type": "action_result", "request_id": request_id})
            await control.from_helper(self.device, {"type": "action_result", "request_id": request_id,
                                                    "ok": ok, "error": "outside", "started": started})
            if frame == "error":  # the helper's capture failed after the action ran
                self.hub.snap_waiters[request_id][1].set_exception(ValueError("capture failed"))
            elif frame:
                self.hub.snap_waiters[request_id][1].set_result(self.share.frames[-1])

        move = ControlAction(kind="move", x=1, y=1)
        _, frame, cmd, stale = (await asyncio.gather(control.action("line", "agent-a", move), answer()))[0]
        self.assertEqual((cmd, stale), ({"kind": "move", "x": -97, "y": 3}, False))
        with self.assertRaisesRegex(ValueError, "refused the action: outside"):
            await asyncio.gather(control.action("line", "agent-a", move), answer(ok=False))
        grant = control.grants["share"]
        self.assertEqual([entry[1] for entry in grant.audit], ["move (-97,3)"])  # refusals: no entry
        drag = ControlAction(kind="drag", x1=0, y1=0, x2=9, y2=9)
        with self.assertRaisesRegex(ValueError, "interrupted: outside"):  # partly injected: audited
            await asyncio.gather(control.action("line", "agent-a", drag), answer(ok=False, started=True))
        self.assertEqual(grant.audit[-1][1], "drag (-99,1)→(-81,19) (interrupted: outside)")
        with unittest.mock.patch("partyline.screen_control.FRAME_TIMEOUT", 0):
            result = await asyncio.gather(control.action("line", "agent-a", move), answer(frame=False))
        self.assertTrue(result[0][3])
        result = await asyncio.gather(control.action("line", "agent-a", move), answer(frame="error"))
        self.assertTrue(result[0][3])  # a failed capture returns the latest frame, marked stale
        with unittest.mock.patch("partyline.screen_control.ACTION_TIMEOUT", 0):
            with self.assertRaisesRegex(ValueError, "did not answer"):
                await control.action("line", "agent-a", move)
        self.assertEqual(grant.audit[-1][1], "move (-97,3) (unconfirmed)")
        grant.status = "revoked"  # late entries after a revoke post at once
        await control._audit(grant, "line", "agent-a", "click left (1,1) (interrupted: x)")
        self.assertIn("click left (1,1) (interrupted: x)", self.db.list_messages("line")[-1]["body"])
        grant.status = "active"
        task = asyncio.create_task(control.action("line", "agent-a", move))
        await until(lambda: control.waiters)
        await self.hub.stop_share("share", "stopped")
        with self.assertRaisesRegex(ValueError, "screen sharing has stopped"):
            await task
        self.assertEqual((control.waiters, self.hub.snap_waiters), ({}, {}))

    def test_rate_limits_and_session_cap(self):
        clock = ManualTime()
        control = ControlHub(SimpleNamespace(), ControlLimits(per_second=2, max_text=5, per_session=3),
                             clock=clock)
        grant = Grant("share", "a", "a", status="active")
        control._spend(grant)
        control._spend(grant)
        with self.assertRaisesRegex(ValueError, "at most 2 actions per second"):
            control._spend(grant)
        clock.advance(1)
        control._spend(grant)
        clock.advance(1)
        with self.assertRaisesRegex(ValueError, "at most 3 actions per share"):
            control._spend(grant)
        self.assertEqual(ControlLimits.from_env({"PARTYLINE_CONTROL_RATE": "4",
                                                 "PARTYLINE_CONTROL_MAX_TEXT": " ",
                                                 "PARTYLINE_CONTROL_SESSION_ACTIONS": "9"}),
                         ControlLimits(4, 500, 9))
        for bad in ("0", "-1", "ten"):
            with self.assertRaises(ValueError):
                ControlLimits.from_env({"PARTYLINE_CONTROL_RATE": bad})
        frame = BufferedFrame(b"", 0, dict(REGION), 200, 100, None, "image/png")
        with self.assertRaisesRegex(ValueError, "5 characters"):
            command(ControlAction(kind="type", text="toolong"), frame, 5, "Linux")

    async def test_audit_batches_and_flushes_on_end(self):
        control = self.hub.control
        grant = control.grants["share"] = Grant("share", "a", "a", status="active")
        for index in range(105):
            await control._audit(grant, "line", "a" if index < 102 else "b", f"click left ({index},0)")
        bodies = [row["body"] for row in self.db.list_messages("line")]
        self.assertEqual(len(bodies), 1)
        self.assertTrue(bodies[0].startswith("Agent control audit — a: click left (0,0) · click left (1,0)"))
        self.assertEqual(len(grant.audit), 5)
        await self.hub.stop_share("share", "stopped")
        bodies = [row["body"] for row in self.db.list_messages("line")]
        self.assertIn("· b: click left (102,0)", bodies[-3])
        self.assertEqual(bodies[-2], "Agent control ended with the share (stopped).")

    async def test_folded_moves_still_trigger_audit_batch(self):
        control = self.hub.control
        grant = control.grants["share"] = Grant("share", "a", "a", status="active")
        for index in range(100):
            await control._audit(grant, "line", "a", f"move ({index},0)")
        self.assertEqual(grant.audit, [])
        bodies = [row["body"] for row in self.db.list_messages("line")]
        self.assertTrue(bodies[-1].startswith("Agent control audit — a: move (99,0) ×100"))

    async def test_audit_recovery_and_failed_publish(self):
        from partyline.screen_audit import recover
        control = self.hub.control
        grant = control.grants["share"] = Grant("share", "a", "a", status="active")
        for index in range(3):
            await control._audit(grant, "line", "a", f"click left ({index},0)")
        with unittest.mock.patch("partyline.screen_audit._body", side_effect=RuntimeError("failed")):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                await control.flush(grant, "line")
        self.assertEqual(len(grant.audit), 3)
        self.assertIsNotNone(grant.flusher)
        self.assertEqual(self.db._exec("SELECT count(*) FROM screen_control_audit "
                                       "WHERE message_id IS NULL").fetchone()[0], 3)
        register_screen_routes(FastAPI(), self.runtime,
                               MediaStore(self.db, Path(self.tmp.name) / "media"))
        recover(self.db)  # recovery is idempotent
        bodies = [row["body"] for row in self.db.list_messages("line")]
        self.assertEqual(len(bodies), 1)
        self.assertIn("click left (0,0)", bodies[0])
        self.assertIn("click left (2,0)", bodies[0])
        self.assertIn("audit sha256:", bodies[0])
        entries = self.db._exec("SELECT * FROM screen_control_audit ORDER BY id").fetchall()
        self.assertEqual(entries[0]["previous_hash"], "")
        self.assertEqual(entries[1]["previous_hash"], entries[0]["entry_hash"])
        self.assertEqual(entries[2]["previous_hash"], entries[1]["entry_hash"])
        self.assertIn(entries[2]["entry_hash"], bodies[0])
        self.assertEqual(self.db._exec("SELECT count(*) FROM screen_control_audit "
                                       "WHERE message_id IS NULL").fetchone()[0], 0)

    async def test_revoke_paths(self):
        control = self.hub.control
        control.expect(self.share, "person")
        self.assertEqual(control.view(self.share)["holder"], None)
        await control.from_helper(self.device, {"type": "control_revoked", "share_id": "share"})
        self.assertNotIn("share", control.grants)
        await control.from_helper(self.device, {"type": "control_granted", "share_id": "nope"})
        self.assertFalse(await control.revoke(self.share, "nothing"))
        control.grants["share"] = Grant("share", "a", "a", status="active")
        await control.from_helper(self.device, {"type": "control_revoked", "share_id": "share",
                                                "reason": "Ctrl+Alt+Esc pressed"})
        self.assertEqual(control.grants["share"].reason, "Ctrl+Alt+Esc pressed")
        self.assertEqual(self.sent, [])  # the helper revoked it; nothing is echoed back
        self.assertFalse(await control.revoke(self.share, "again"))


class CoordinateTest(unittest.TestCase):
    def test_frame_pixels_map_into_the_region_and_round_trip(self):
        for region, size in ((dict(x=-1920, y=-200, width=1920, height=1080), (1280, 720)),
                             (dict(x=-100, y=0, width=200, height=100), (200, 100)),
                             (dict(x=2560, y=0, width=2880, height=1800), (1280, 800)),
                             (dict(x=-7, y=-3, width=17, height=13), (11, 9))):
            frame = BufferedFrame(b"", 0, region, *size, None, "image/png")
            for fx in range(0, size[0], max(1, size[0] // 37)):
                for fy in (0, size[1] // 2, size[1] - 1):
                    x, y = to_os(fx, fy, frame)
                    self.assertTrue(region["x"] <= x < region["x"] + region["width"])
                    self.assertTrue(region["y"] <= y < region["y"] + region["height"])
                    frame.pointer = {"x": x, "y": y, "visible": True}
                    self.assertEqual(pointer_coordinates(frame)["frame"], {"x": fx, "y": fy})
            for fx, fy in ((-1, 0), (0, -1), (size[0], 0), (0, size[1])):
                with self.assertRaisesRegex(ValueError, "outside the shared region"):
                    to_os(fx, fy, frame)
        frame = BufferedFrame(b"", 0, dict(x=-1920, y=-200, width=1920, height=1080), 1280, 720, None, "")
        self.assertEqual(to_os(0, 0, frame), (-1920, -200))
        self.assertEqual(to_os(1279, 719, frame), (-1, 879))
        drag = command(ControlAction(kind="drag", x1=0, y1=0, x2=640, y2=360), frame, 500, "Linux")
        self.assertEqual(drag, {"kind": "drag", "x1": -1920, "y1": -200, "x2": -960, "y2": 340})
        with self.assertRaises(ValueError):
            to_os(None, 0, frame)


class DescribeTest(unittest.TestCase):
    def test_audit_entries(self):
        from partyline.screen_control_actions import describe
        frame = BufferedFrame(b"", 0, dict(x=0, y=0, width=10, height=10), 10, 10, None, "")

        def entry(**fields):
            return describe(command(ControlAction(**fields), frame, 500, "Linux"))

        self.assertEqual(entry(kind="click", x=1, y=2, button="right", double=True),
                         "double-click right (1,2)")
        self.assertEqual(entry(kind="drag", x1=0, y1=0, x2=9, y2=9), "drag (0,0)→(9,9)")
        self.assertEqual(entry(kind="scroll", x=1, y=1, dy=-2), "scroll 0,-2 at (1,1)")
        self.assertEqual(entry(kind="key", keys="Control+Return"), "key ctrl+enter")
        self.assertEqual(entry(kind="type", text="a\tb\n" + "x" * 50),
                         "type `a⇥b⏎" + "x" * 36 + "…` (54 chars)")
        for bad in (dict(kind="type"), dict(kind="type", text="\x07"), dict(kind="scroll", x=1, y=1, dx=51),
                    dict(kind="move")):
            with self.assertRaises(ValueError, msg=bad):
                command(ControlAction(**bad), frame, 500, "Linux")


class McpControlToolsTest(unittest.TestCase):
    def test_tools_gate_validate_and_route(self):
        self.assertEqual(tools_control.tool_list({"actions": ["read"]}), [])
        names = [tool["name"] for tool in tools_control.tool_list({"actions": ["write"]})]
        self.assertEqual(names, ["screen_element_action", "screen_control_request", "screen_click",
                                 "screen_move", "screen_drag", "screen_scroll", "screen_type", "screen_key"])
        calls = []
        client = SimpleNamespace(home="line/1", request=lambda *args: calls.append(args) or {"ok": 1})
        state = {"actions": ["write"]}
        tools_control.call(client, "screen_control_request", {}, state)
        tools_control.call(client, "screen_click", {"x": 1, "y": 2, "double": True}, state)
        self.assertEqual(calls, [
            ("POST", "/api/conversations/line%2F1/screen-control/request"),
            ("POST", "/api/conversations/line%2F1/screen-control/action",
             {"kind": "click", "x": 1, "y": 2, "double": True})])
        with self.assertRaises(ValueError):
            tools_control.call(client, "screen_type", {"text": "x" * 501}, state)
        with self.assertRaises(ValueError):
            tools_control.call(client, "screen_move", {"x": 1, "y": 2, "z": 3}, state)
        with self.assertRaises(ApiError):
            tools_control.call(client, "screen_move", {"x": 1, "y": 2}, {"actions": ["read"]})

    def test_element_action_mcp_routes_value_and_requires_write(self):
        calls = []
        def request(*args, **kwargs):
            calls.append((args, kwargs))
            return {"status": "completed"}
        client = SimpleNamespace(home="line", request=request)
        action = {"element_id": "abc", "action": "set_value", "value": "text"}
        result = tools_control.call(client, "screen_element_action", action, {"actions": ["write"]})
        self.assertEqual("completed", result["status"])
        self.assertEqual(("POST", "/api/conversations/line/screen-control/element-action", action),
                         calls[0][0])
        self.assertEqual({"timeout": 40}, calls[0][1])
        with self.assertRaises(ApiError):
            tools_control.call(client, "screen_element_action", action, {"actions": ["read"]})
