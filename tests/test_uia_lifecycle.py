"""Window-action lifecycle and revocation races with event-driven fake providers."""
import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from partyline_helper.client import Session
from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_action_worker import ActionWorker, run_action
from partyline_helper.uia_gate import DispatchGate
from partyline_helper.uia_identity import element_id
from partyline_helper.uia_task import WindowTask
from tests.screen_helper_fakes import FakeDesktop, FakeSocket, FakeTerminal
from tests.test_uia_worker import Provider


def session_fixture():
    gate = DispatchGate()
    gate.grant()
    grant = {"hwnd": 10, "pid": 42, "title": "Target", "process": "app"}
    audit = SimpleNamespace(append=Mock(), ensure_writable=Mock())
    window = SimpleNamespace(gate=gate, grant=grant, elements={"id": {"name": "field"}}, revoke=Mock())
    session = SimpleNamespace(window=window, control=SimpleNamespace(granted=True), accepted=True,
                              share={"share_id": "s"}, tools=SimpleNamespace(audit=audit), send=AsyncMock())
    return session


class WorkerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_refuses_stale_and_every_control_condition_and_audits(self):
        for change, error in [({"element_id": "missing"}, "stale"),
                              ({"share_id": "other"}, "revoked"),
                              ({"accepted": False}, "revoked"),
                              ({"granted": False}, "revoked"),
                              ({"gate_revoked": True}, "revoked")]:
            with self.subTest(change=change):
                session = session_fixture()
                message = {"element_id": "id", "action": "toggle", "share_id": "s"}
                for key, value in change.items():
                    if key in message:
                        message[key] = value
                    elif key == "accepted":
                        session.accepted = value
                    elif key == "granted":
                        session.control.granted = value
                    else:
                        session.window.gate.invalidate()
                result = await ActionWorker(session).perform(message)
                self.assertIn(error, result["error"])
                session.tools.audit.append.assert_called_once()

    async def test_closed_window_revokes_and_secure_desktop_pauses(self):
        for error in ("window closed", "secure desktop active"):
            with self.subTest(error=error):
                session = session_fixture()
                runner = lambda *_, failure=error: {"status": "failed", "error": failure}  # noqa: E731
                worker = ActionWorker(session, runner=runner)
                result = await worker.perform({"element_id": "id", "action": "toggle", "share_id": "s"})
                self.assertEqual(error, result["error"])
                if error == "window closed":
                    session.window.revoke.assert_called_once_with(error)
                else:
                    self.assertTrue(session.window.gate.revoked.is_set())
                session.tools.audit.append.assert_called_once()

    async def test_abandoned_action_permits_reads_but_refuses_another_action(self):
        session = session_fixture()
        entered, finish = asyncio.Event(), asyncio.Event()
        async def snapshot(options=None):
            entered.set()
            await finish.wait()
            return {"elements": []}
        session.window.snapshot = snapshot
        worker = WindowTask(session)
        # A timed-out worker is still in the application.
        worker.actions.task = asyncio.get_running_loop().create_future()
        worker.actions.abandoned = True
        await worker.submit("read")
        await entered.wait()
        message = {"request_id": "action", "element_id": "id", "action": "toggle"}
        await worker.submit_action(message)
        result = session.send.await_args.kwargs
        self.assertEqual("previous action still running in the app", result["error"])
        self.assertEqual("action", result["request_id"])
        session.tools.audit.append.assert_called_once()
        finish.set()
        await worker.task
        session.send.assert_awaited_with("window_elements", request_id="read", elements=[])
        worker.actions.task.cancel()
        await worker.close()

    async def test_stop_share_is_handled_while_pattern_call_is_running(self):
        socket = FakeSocket()
        session = Session(socket, FakeDesktop(), FakeTerminal(), "desktop")
        session.share = {"share_id": "s"}
        session.pending_id = "s"
        session.accepted = True
        session.control.granted = True
        session.control.share_id = "s"
        session.tools.audit = SimpleNamespace(append=Mock(), ensure_writable=Mock())
        session.window.grant = {"hwnd": 10, "pid": 42, "title": "Target", "process": "app"}
        session.window.elements = {"id": {"name": "field"}}
        session.window.gate.grant()
        entered, finish = threading.Event(), threading.Event()
        def runner(access, grant, generation, message):
            def pattern():
                entered.set()
                finish.wait()
            _, revoked = access.gate.dispatch(generation, pattern)
            return {"status": "completed", "revoked_during": revoked}
        session.window_task.actions.runner = runner
        message = {"type": "window_element_action", "request_id": "r", "share_id": "s",
                   "element_id": "id", "action": "toggle"}
        await session.dispatch(message)
        await asyncio.to_thread(entered.wait)
        await session.dispatch({"type": "stop_share", "share_id": "s"})
        self.assertFalse(session.control.granted)
        self.assertEqual("s", (await socket.next("share_stopped"))["share_id"])
        self.assertTrue(session.window.gate.revoked.is_set())
        finish.set()
        result = await socket.next("window_element_result")
        self.assertTrue(result["revoked_during"])
        await session.window_task.close()

    async def test_reread_text_is_bounded(self):
        provider = Provider()
        original = provider.properties
        def properties(node):
            result = original(node)
            result.update(name="n" * 500, value="v" * 500)
            return result
        provider.properties = properties
        gate = DispatchGate()
        generation = gate.grant()
        grant = {"hwnd": 1, "pid": 2}
        access = SimpleNamespace(gate=gate, list_windows=lambda: [grant])
        message = {"element_id": element_id(provider, 1, [0]), "action": "set_value", "value": "new"}
        result = run_action(access, grant, generation, message, factory=lambda _: provider)
        self.assertEqual(160, len(result["element"]["name"]))
        self.assertEqual(160, len(result["element"]["value"]))


class WindowWatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_pause_and_regrant_without_waiting_real_time(self):
        session = session_fixture()
        access = WindowAccess(session, platform="win32")
        access.grant = session.window.grant
        access.gate.grant()
        ticks, entered = asyncio.Queue(), asyncio.Queue()
        async def sleep(_):
            entered.put_nowait(True)
            await ticks.get()
        access.check = AsyncMock(side_effect=["secure desktop active", None, "window closed"])
        session.status = SimpleNamespace(window_title="Target", changed=Mock())
        watch = asyncio.create_task(access.watch(sleep=sleep))
        await entered.get()
        ticks.put_nowait(True)
        await entered.get()
        self.assertTrue(access.gate.revoked.is_set())
        ticks.put_nowait(True)
        await entered.get()
        self.assertFalse(access.gate.revoked.is_set())
        ticks.put_nowait(True)
        await entered.get()
        self.assertIsNone(access.grant)
        watch.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await watch
