"""Local two-step consent and isolated per-window workers, with event-driven transport."""
import asyncio
import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline_helper.client import Session
from partyline_helper.window_shares import WindowShares
from partyline_helper.window_target_picker import select_target
from tests.screen_helper_fakes import FakeDesktop, FakeSocket, FakeTerminal


TARGET = {"attachment_id": "a", "name": "agent", "preset": "Codex",
          "line_id": "alpha", "line_name": "Alpha"}
WINDOW = {"hwnd": 10, "pid": 42, "title": "Editor", "process": "editor.exe"}


class WindowSharesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.socket = FakeSocket()
        self.session = Session(self.socket, FakeDesktop(), FakeTerminal(), "Desktop")
        self.session.tools.audit = SimpleNamespace(append=Mock(), ensure_writable=Mock())
        self.manager = WindowShares(self.session, window_picker=lambda: dict(WINDOW),
                                    target_picker=lambda _: TARGET)
        self.session.windows = self.manager
        self.targets = {"request_id": "targets", "lines": [
            {"line_id": "alpha", "line_name": "Alpha", "processes": [TARGET]}]}
        self.manager.request = AsyncMock(side_effect=[self.targets, {"ok": True, "target": TARGET}])
        checking = patch("partyline_helper.window_shares.WindowAccess.check",
                         new=AsyncMock(return_value=None))
        checking.start()
        self.addCleanup(checking.stop)

    async def asyncTearDown(self):
        await self.manager.close()

    async def test_cancel_either_picker_or_server_refusal_never_grants(self):
        self.manager.window_picker = lambda: None
        await self.manager.choose()
        self.manager.request.assert_not_awaited()
        self.manager.window_picker = lambda: dict(WINDOW)
        self.manager.target_picker = lambda _: None
        with patch("partyline_helper.window_shares.unmark") as unmark:
            await self.manager.choose()
            unmark.assert_called_once_with(WINDOW)
        self.assertFalse(self.manager.grants)
        self.manager.target_picker = lambda _: TARGET
        self.manager.request = AsyncMock(side_effect=[self.targets, {"ok": False}])
        await self.manager.choose()
        self.assertFalse(self.manager.grants)
        self.assertFalse(self.session.status.window_grants)

    async def test_two_windows_have_independent_elements_workers_and_revoke(self):
        self.manager.request = AsyncMock(side_effect=[self.targets, {"ok": True, "target": TARGET}] * 2)
        await self.manager.choose()
        first = next(iter(self.manager.grants))
        self.manager.window_picker = lambda: {**WINDOW, "hwnd": 20, "title": "Browser"}
        await self.manager.choose()
        second = next(g for g in self.manager.grants if g != first)
        self.assertEqual(2, len(self.session.status.window_grants))
        for ident in (first, second):
            access = self.manager.grants[ident]["access"]
            access.snapshot = AsyncMock(return_value={"elements": [{"id": ident}]})
            await self.manager.dispatch(
                {"type": "read_window_elements", "request_id": ident, "grant_id": ident})
            await self.manager.grants[ident]["worker"].task
            response = await self.socket.next("window_elements")
            self.assertEqual([{"id": ident}], response["elements"])
        first_access = self.manager.grants[first]["access"]
        await self.manager.receive({"type": "revoke_window", "grant_id": first})
        self.assertTrue(first_access.gate.revoked.is_set())
        self.assertEqual([second], list(self.manager.grants))
        self.assertIn("Browser → @agent «Alpha»", self.session.status.label)
        self.manager.revoke_all()
        self.assertFalse(self.manager.grants)
        self.assertIsNone(self.session.status.window_title)
        await self.manager.close()
        self.assertEqual("revoked by the person", (await self.socket.next("window_revoked"))["reason"])

    async def test_local_close_ends_only_its_grant_and_action_needs_that_window_snapshot(self):
        await self.manager.choose()
        ident, entry = next(iter(self.manager.grants.items()))
        entry["access"].elements = {"id": {"name": "Field"}}
        entry["worker"].actions.runner = lambda *_: {"status": "completed"}
        # A window grant authorizes UIA independently of pixel sharing / pointer control.
        self.assertFalse(self.session.accepted)
        await self.manager.dispatch({"type": "window_element_action", "request_id": "act", "grant_id": ident,
                                     "element_id": "id", "action": "toggle"})
        await entry["worker"].task
        self.assertEqual("completed", (await self.socket.next("window_element_result"))["status"])
        entry["access"].revoke("window closed")
        self.assertFalse(self.manager.grants)
        await self.manager.dispatch({"type": "read_window_elements", "request_id": "old", "grant_id": ident})
        response = await self.socket.next("window_elements")
        self.assertEqual("consent revoked", response["elements_unavailable"])
        await self.manager.close()
        revoked = await self.socket.next("window_revoked")
        self.assertEqual(ident, revoked["grant_id"])
        self.assertEqual("window closed", revoked["reason"])

    async def test_pending_picker_stop_all_prevents_late_consent(self):
        selected, finish = asyncio.Event(), asyncio.Event()
        async def request(kind, **fields):
            if kind == "list_share_targets":
                selected.set()
                await finish.wait()
                return self.targets
            return {"ok": True, "target": TARGET}
        self.manager.request = request
        task = asyncio.create_task(self.manager.choose())
        await selected.wait()
        await self.manager.choose()  # overlapping picker cannot open another dialog
        self.manager.revoke_all()
        finish.set()
        await task
        self.assertFalse(self.manager.grants)

    async def test_request_correlation_and_session_dispatch(self):
        manager = WindowShares(self.session)
        self.session.windows = manager
        task = asyncio.create_task(manager.request("list_share_targets"))
        request = await self.socket.next("list_share_targets")
        await self.session.dispatch({"type": "share_targets", "request_id": "wrong", "lines": []})
        self.assertFalse(task.done())
        await self.session.dispatch(
            {"type": "share_targets", "request_id": request["request_id"], "lines": []})
        self.assertEqual([], (await task)["lines"])
        self.assertFalse(manager.waiters)
        await self.session.dispatch(
            {"type": "read_window_elements", "grant_id": "missing", "request_id": "r"})
        response = await self.socket.next("window_elements")
        self.assertEqual("consent revoked", response["elements_unavailable"])
        await manager.close()

    async def test_watch_pauses_resumes_and_closes_only_the_matching_window(self):
        await self.manager.choose()
        ident, entry = next(iter(self.manager.grants.items()))
        access = entry["access"]
        access.check = AsyncMock(side_effect=["secure desktop active", None, "window closed"])
        entered, ticks = asyncio.Queue(), asyncio.Queue()
        async def sleep(_):
            entered.put_nowait(True)
            await ticks.get()
        self.session.sleep = sleep
        watch = asyncio.create_task(self.manager.watch())
        await entered.get()
        for revoked in (True, False, True):
            ticks.put_nowait(True)
            await entered.get()
            self.assertEqual(revoked, access.gate.revoked.is_set())
        self.assertNotIn(ident, self.manager.grants)
        self.assertEqual("window closed", (await self.socket.next("window_revoked"))["reason"])
        watch.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await watch

    async def test_stop_during_server_registration_withdraws_late_grant(self):
        async def request(kind, **fields):
            if kind == "list_share_targets":
                return self.targets
            self.manager.revoke_all()
            return {"ok": True, "target": TARGET}
        self.manager.request = request
        await self.manager.choose()
        self.assertFalse(self.manager.grants)
        self.assertTrue((await self.socket.next("window_revoked"))["grant_id"])


class TargetPickerTests(unittest.TestCase):
    def test_native_subprocess_selection_cancel_and_failure(self):
        lines = [{"line_id": "alpha", "line_name": "Alpha", "processes": [TARGET]}]
        def select(command, **kwargs):
            path = Path(command[-1])
            self.assertEqual(lines, json.loads(path.read_text())["lines"])
            path.write_text(json.dumps({"selected": TARGET}))
        self.assertEqual(TARGET, select_target(lines, run=select))
        self.assertIsNone(select_target(lines, run=lambda *_, **__: None))
        self.assertIsNone(select_target([], run=Mock(side_effect=AssertionError)))
        with patch("partyline_helper.window_target_picker.sys.frozen", True, create=True):
            self.assertEqual(TARGET, select_target(lines, run=select))
        self.assertIsNone(select_target(lines, run=Mock(side_effect=OSError)))
        self.assertIsNone(select_target(lines, run=Mock(side_effect=subprocess.TimeoutExpired("picker", 65))))

    def test_picker_temp_file_and_selection_strip_private_server_fields(self):
        secret = "private-hook-secret"
        target = {**TARGET, "runtime_owner": secret}
        lines = [{"line_id": "alpha", "line_name": "Alpha", "runtime_owner": secret,
                  "processes": [target]}]
        def choose(command, **kwargs):
            path = Path(command[-1])
            content = path.read_text()
            self.assertNotIn(secret, content)
            self.assertNotIn("runtime_owner", content)
            path.write_text(json.dumps({"selected": target}))
        self.assertEqual(TARGET, select_target(lines, run=choose))
