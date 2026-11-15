"""Dropped connections, new grants and explicit reload share one fake-clock prompt budget."""
import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from partyline.screen_chrome_state import ChromeState
from partyline_helper.cdp_transport import RETRY_SECONDS
from partyline_helper.uia_task import WindowTask
from tests.cdp_fakes import Fixture, Socket
from tests.test_cdp_settle import Clock


class ReconnectTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        self.clock = Clock()
        self.f.browser.clock = self.clock

    async def refuse(self):
        self.f.connector.side_effect = OSError("denied")
        self.assertFalse(await self.f.browser.ensure())
        self.assertEqual(self.f.browser.state, "refused")
        self.f.connector.side_effect = None

    async def test_dropped_socket_reconnects_on_next_read_after_shared_cooldown(self):
        await self.f.read()
        page = self.f.chrome.pages[self.f.access]["a"]
        await self.f.socket.close()
        await self.f.browser.reader
        self.assertEqual(self.f.browser.state, "disconnected")
        self.assertFalse(page.live)
        self.assertEqual(ChromeState(state="disconnected").state, "disconnected")
        self.clock.advance(18)
        worker = WindowTask(self.f.access.session)
        self.f.access.snapshot = AsyncMock(return_value={"elements": []})
        result = await worker.snapshot({}, {})
        self.assertEqual(result["source"], "uia")
        self.assertIn("Chrome connection dropped", result["source_reason"])
        self.assertIn("next attempt allowed in 42 s", result["source_reason"])
        self.assertEqual(self.f.connector.await_count, 1)
        self.clock.advance(42)
        self.f.socket = Socket()
        self.f.connector.return_value = self.f.socket
        self.assertIsNone(await self.f.chrome.read(self.f.access, {}, {}))
        await self.f.chrome.connecting
        self.assertEqual(self.f.browser.state, "connected")
        self.assertEqual((await self.f.chrome.read(self.f.access, {}, {}))["source"], "cdp")
        self.assertEqual(self.f.connector.await_count, 2)

    async def test_refusal_needs_a_new_grant_or_reload_even_after_cooldown(self):
        await self.refuse()
        self.clock.advance(RETRY_SECONDS)
        self.assertFalse(await self.f.browser.ensure())
        self.assertIsNone(await self.f.chrome.read(self.f.access, {}, {}))
        self.assertIsNone(self.f.chrome.connecting)
        self.assertEqual(self.f.connector.await_count, 1)
        self.assertIn("share a window or use reload", self.f.chrome.reasons[self.f.access])

    async def test_repeated_reads_grants_and_concurrent_requests_cannot_storm_prompts(self):
        self.f.connector.side_effect = OSError("denied")
        for _ in range(20):
            self.f.chrome.start(self.f.access, retry=True)
        await self.f.chrome.connecting
        self.assertEqual(self.f.connector.await_count, 1)
        for _ in range(20):
            self.f.chrome.start(self.f.access, retry=True)
            self.assertFalse(await self.f.browser.ensure())
        self.clock.advance(59.1)
        self.assertFalse(await self.f.browser.ensure())
        self.assertIn("next attempt allowed in 1 s", self.f.browser.reason())
        self.assertEqual(self.f.connector.await_count, 1)
        self.clock.advance(0.9)
        await asyncio.gather(*(self.f.browser.ensure() for _ in range(50)))
        self.assertEqual(self.f.connector.await_count, 2)
        self.assertEqual(self.f.browser.state, "refused")

    async def test_reload_retries_refusal_but_respects_prompt_limit(self):
        await self.refuse()
        message = dict(action="reload", element_id="page")
        result = await self.f.chrome.action(self.f.access, message)
        self.assertEqual(result["status"], "failed")
        self.assertIn("next attempt allowed in 60 s", result["error"])
        self.assertEqual(self.f.connector.await_count, 1)
        self.clock.advance(RETRY_SECONDS)
        result = await self.f.chrome.action(self.f.access, message)
        self.assertEqual(result["status"], "failed")
        self.assertIn("Awaiting Chrome approval", result["error"])
        await self.f.chrome.connecting
        self.assertFalse(any(m["method"] == "Page.reload" for m in self.f.socket.calls))
        with patch("partyline_helper.cdp_settle.Quiet.wait", AsyncMock(return_value="quiet")):
            result = await self.f.chrome.action(self.f.access, message)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.f.connector.await_count, 2)
        self.assertEqual(sum(m["method"] == "Page.reload" for m in self.f.socket.calls), 1)

    def grant_setup(self):
        self.f.shares.outline_factory = Mock(return_value=SimpleNamespace(start=AsyncMock(), close=Mock()))
        self.f.shares.start_events = AsyncMock()
        self.f.shares.request = AsyncMock(side_effect=[
            {"request_id": "targets", "lines": [{"line_id": "line", "line_name": "Line",
                                                 "standing_access": True}]},
            {"ok": True, "target": {"line_id": "line", "line_name": "Line"}}])

    async def test_refusal_then_standing_attach_retries_without_local_picker(self):
        from partyline_helper.window_standing_attach import attach
        await self.refuse()
        self.clock.advance(RETRY_SECONDS)
        self.grant_setup()
        self.f.session.window_access_enabled = True
        self.f.session.window_access_audit = SimpleNamespace(append=Mock())
        self.f.session.standing_window_rows = {"1": {**self.f.window, "marker": "window-lifetime"}}
        with patch("partyline_helper.uia_access.WindowAccess.check", AsyncMock(return_value=None)):
            await attach(self.f.shares, dict(request_id="a", window="1", line="line", line_id="line"))
        await self.f.chrome.connecting
        self.assertEqual(self.f.browser.state, "connected")
        self.assertEqual(self.f.connector.await_count, 2)
        self.assertTrue(any(call.kwargs.get("ok") for call in self.f.session.send.await_args_list))

    async def test_new_local_share_uses_the_same_retry_allowance(self):
        await self.refuse()
        self.clock.advance(RETRY_SECONDS)
        self.grant_setup()
        self.f.shares.window_picker = lambda: self.f.window.copy()
        self.f.shares.target_picker = lambda _: {"line_id": "line", "line_name": "Line"}
        with patch("partyline_helper.uia_access.WindowAccess.check", AsyncMock(return_value=None)):
            await self.f.shares.choose()
        await self.f.chrome.connecting
        self.assertEqual(self.f.browser.state, "connected")
        self.assertEqual(self.f.connector.await_count, 2)


    async def test_reload_with_blocked_allow_prompt_keeps_window_queue_available(self):
        await self.refuse()
        self.clock.advance(RETRY_SECONDS)
        entered, released = asyncio.Event(), asyncio.Event()
        async def connect(*args, **kwargs):
            entered.set()
            await released.wait()
            return self.f.socket
        self.f.connector.side_effect = connect
        worker = WindowTask(self.f.access.session)
        self.addAsyncCleanup(worker.close)
        self.f.shares.grants["g"]["worker"] = worker
        self.f.access.snapshot = AsyncMock(return_value={"elements": [{"id": "toolbar"}]})
        with patch("partyline_helper.screen_access_audit.audit_window"):
            await worker.submit_action(dict(action="reload", element_id="page", request_id="reload"))
            started = asyncio.create_task(entered.wait())
            await asyncio.wait((worker.task, started), return_when=asyncio.FIRST_COMPLETED)
            await started
            self.assertTrue(worker.task.done(), "reload held the window queue on Chrome approval")
            await worker.task
            self.assertFalse(worker.busy())
            replies = [c.kwargs for c in self.f.session.send.await_args_list
                       if c.kwargs.get("request_id") == "reload"]
            self.assertEqual(replies[-1]["status"], "failed")
            self.assertIn("Awaiting Chrome approval", replies[-1]["error"])
            await worker.submit("read")
            await worker.task
            replies = [c.kwargs for c in self.f.session.send.await_args_list
                       if c.kwargs.get("request_id") == "read"]
            self.assertEqual(replies[-1]["source"], "uia")
            self.assertNotIn("elements_unavailable", replies[-1])
            self.f.access.elements["toolbar"] = {"id": "toolbar"}
            worker.actions.perform = AsyncMock(return_value={"status": "completed"})
            await worker.submit_action(dict(action="invoke", element_id="toolbar", request_id="invoke"))
            await worker.task
            worker.actions.perform.assert_awaited_once()
            self.assertFalse(released.is_set())
            self.assertFalse(self.f.chrome.connecting.done())
            self.assertEqual(self.f.connector.await_count, 2)
            self.f.shares.revoke("g", notify=False)
            await asyncio.gather(self.f.chrome.connecting, return_exceptions=True)
            self.assertTrue(self.f.chrome.connecting.done())
            self.assertFalse(worker.busy())
            self.assertFalse(self.f.socket.calls)

    async def test_revoked_reload_cannot_start_approval(self):
        await self.refuse()
        self.clock.advance(RETRY_SECONDS)
        self.f.access.gate.invalidate()
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "consent revoked")
        self.assertEqual(self.f.connector.await_count, 1)
