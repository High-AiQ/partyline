"""Crashes, recovery and consent races over the real multiplexer with a fake renderer and clock."""
import asyncio
import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from partyline_helper.cdp_settle import Quiet
from partyline_helper.cdp_transport import PageUnavailable
from partyline_helper.uia_task import WindowTask
from tests.cdp_fakes import Fixture, Socket
from tests.screen_helper_fakes import checkpoint
from tests.test_cdp_settle import Clock


class Deadline:
    """Inject a one-shot command deadline into the transport without wall time."""
    def __init__(self, clock, delay):
        self.clock, self.delay, self.expired = clock, delay, False

    async def __aenter__(self):
        self.task = asyncio.current_task()
        def expire():
            self.expired = True
            self.task.cancel()
        self.timer = self.clock.call_later(self.delay, expire)
        return self

    async def __aexit__(self, kind, error, tb):
        self.timer.cancel()
        if self.expired and kind is asyncio.CancelledError:
            self.task.uncancel()
            raise TimeoutError from error


class CrashSocket(Socket):
    def __init__(self):
        super().__init__()
        self.crashed, self.sessions = set(), {}
        self.attaches = 0
        self.hung = asyncio.Event()

    async def send(self, raw):
        m = json.loads(raw)
        target = self.sessions.get(m.get("sessionId"))
        if target in self.crashed and m["method"] in (
                "Runtime.evaluate", "Accessibility.getFullAXTree", "Page.getFrameTree"):
            self.calls.append(m)
            self.hung.set()
            return  # Real crashed renderers leave these requests unanswered.

        await super().send(raw)

    def response(self, m):
        if m["method"] == "Target.attachToTarget":
            self.attaches += 1
            session = m["params"]["targetId"] + str(self.attaches)
            self.sessions[session] = m["params"]["targetId"]
            return {"sessionId": session}
        if m["method"] == "Inspector.enable" and self.sessions.get(m.get("sessionId")) in self.crashed:
            self.event("Inspector.targetCrashed", session=m["sessionId"])
        if m["method"] == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "main", "url": "https://example.test/lab"}}}
        if m["method"] in ("Page.navigate", "Page.reload"):
            if self.sessions[m["sessionId"]] in self.crashed:
                self.event("Inspector.targetReloadedAfterCrash", session=m["sessionId"])
            self.crashed.discard(self.sessions[m["sessionId"]])
            self.event("Page.frameNavigated", session=m["sessionId"],
                       frame={"id": "main", "url": "https://example.test/lab"})
        return super().response(m)


class RecoveryTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.f.socket = CrashSocket()
        self.f.connector.return_value = self.f.socket
        self.addAsyncCleanup(self.f.close)
        self.rows = await self.f.read()
        self.page = self.f.chrome.pages[self.f.access]["a"]
        self.clock = Clock()
        self.page.quiet = Quiet(self.clock, self.clock)
        self.task = WindowTask(self.f.access.session)
        self.f.access.snapshot = AsyncMock(return_value={"elements": [{"id": "toolbar", "name": "Reload"}]})

    async def crash(self, method="Inspector.targetCrashed", **params):
        self.f.socket.crashed.add("a")
        self.f.socket.event(method, session=self.page.session, **params)
        await checkpoint()

    async def reload(self):
        waiting = asyncio.Event()
        original = self.page.quiet.wait
        async def wait():
            waiting.set()
            return await original()
        self.page.quiet.wait = wait
        task = asyncio.create_task(self.f.chrome.action(self.f.access,
            dict(action="reload", element_id="page")))
        await waiting.wait()
        await checkpoint()
        self.clock.advance(0.1)
        return await task

    async def test_inspector_and_browser_crash_events_mark_only_the_target(self):
        for method, params in (("Inspector.targetCrashed", {}),
                               ("Target.targetCrashed", {"targetId": "a"}),
                               ("Target.targetInfoChanged",
                                {"targetInfo": {"targetId": "a", "crashed": True}})):
            self.page.page_state = "alive"
            before = self.f.state.count
            await self.crash(method, **params)
            self.assertEqual(self.page.page_state, "crashed")
            self.assertFalse(self.page.nodes)
            self.assertGreater(self.f.state.count, before)
        self.page.page_state = "alive"
        self.f.socket.event("Target.targetCrashed", session=None, targetId="other")
        await checkpoint()
        self.assertEqual(self.page.page_state, "alive")

    async def test_read_after_crash_uses_uia_and_preserves_recovery_metadata(self):
        await self.crash()
        self.f.window["title"] = "Aw, Snap! - Google Chrome"
        result = await self.task.snapshot({}, {})
        self.assertEqual(result["source"], "uia")
        self.assertEqual(result["page_state"], "crashed")
        self.assertEqual(result["elements"][0]["name"], "Reload")
        self.assertIn('action="reload"', result["recovery_hint"])
        self.assertIs(self.f.access.grant, self.page.grant)
        self.assertTrue(self.page.live)

    async def test_crashed_read_reaches_uia_without_waiting_for_a_renderer_timeout(self):
        await self.crash()
        self.f.browser.timeout = lambda delay: Deadline(self.clock, delay)
        before = len(self.f.socket.calls)
        task = asyncio.create_task(self.task.snapshot({}, {}))
        blocked = asyncio.create_task(self.f.socket.hung.wait())
        done, _ = await asyncio.wait((task, blocked), return_when=asyncio.FIRST_COMPLETED)
        try:
            self.assertIn(task, done, "crashed read dispatched an unanswered renderer probe")
            result = await task
            self.assertEqual(result["page_state"], "crashed")
            self.assertEqual(self.clock.now, 0)
            self.assertFalse(any(m["method"] in ("Runtime.evaluate", "Accessibility.getFullAXTree",
                                                 "Page.getFrameTree")
                                 for m in self.f.socket.calls[before:]))
        finally:
            blocked.cancel()
            self.clock.advance(10)
            await asyncio.gather(task, blocked, return_exceptions=True)

    async def test_crashed_fake_commands_hang_until_the_fake_deadline(self):
        from partyline_helper.cdp_transport import CDPError
        await self.crash()
        self.f.browser.timeout = lambda delay: Deadline(self.clock, delay)
        for method in ("Runtime.evaluate", "Accessibility.getFullAXTree", "Page.getFrameTree"):
            self.f.socket.hung.clear()
            task = asyncio.create_task(self.page.raw(method))
            await self.f.socket.hung.wait()
            self.assertFalse(task.done())
            self.clock.advance(10)
            with self.assertRaises(CDPError):
                await task
            self.assertEqual(self.page.page_state, "crashed")

    async def test_crashed_reload_navigates_and_reestablishes_all_observers(self):
        await self.crash()
        result = await self.reload()
        self.assertEqual(result["status"], "completed")
        navigate = next(m for m in self.f.socket.calls if m["method"] == "Page.navigate")
        self.assertEqual(navigate["params"], {"url": "https://example.test/lab"})
        fresh = self.f.chrome.pages[self.f.access]["a"]
        self.assertIsNot(fresh, self.page)
        self.assertTrue(fresh.initialized)
        methods = [m["method"] for m in self.f.socket.calls if m.get("sessionId") == fresh.session]
        for method in ("Page.createIsolatedWorld", "Runtime.addBinding", "Page.setLifecycleEventsEnabled"):
            self.assertIn(method, methods)
        self.assertEqual((await self.f.read())["source"], "cdp")
        self.assertEqual(self.f.connector.await_count, 1)

    async def test_live_reload_uses_page_reload(self):
        result = await self.reload()
        self.assertEqual(result["status"], "completed")
        methods = [m["method"] for m in self.f.socket.calls]
        self.assertIn("Page.reload", methods)
        self.assertNotIn("Page.navigate", methods)

    async def test_manual_reload_is_detected_on_next_read_without_new_consent(self):
        await self.crash()
        self.assertEqual((await self.task.snapshot({}, {}))["source"], "uia")
        self.f.socket.crashed.clear()
        self.f.socket.event("Inspector.targetReloadedAfterCrash", session=self.page.session)
        await checkpoint()
        result = await self.task.snapshot({}, {})
        self.assertEqual(result["source"], "cdp")
        fresh = self.f.chrome.pages[self.f.access]["a"]
        self.assertIsNot(fresh, self.page)
        self.assertTrue(fresh.initialized)
        self.assertEqual(self.f.connector.await_count, 1)
        self.assertNotEqual(result["elements"][1]["id"], self.rows["elements"][1]["id"])

    async def test_detached_session_read_reattaches_without_regrant(self):
        self.f.socket.event("Target.detachedFromTarget", session=None, sessionId=self.page.session)
        await checkpoint()
        self.assertEqual(self.page.page_state, "detached")
        self.assertEqual((await self.f.read())["source"], "cdp")
        self.assertEqual(self.f.socket.attaches, 2)

    async def test_crashed_page_action_is_refused_but_uia_toolbar_actions_dispatch_once(self):
        await self.crash()
        result = await self.f.chrome.action(self.f.access,
            dict(action="invoke", element_id=self.rows["elements"][1]["id"]))
        self.assertEqual(result["status"], "failed")
        self.assertIn("reload", result["error"])
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))
        await self.task.snapshot({}, {})
        self.f.access.elements["toolbar"] = {"id": "toolbar"}
        self.task.actions.perform = AsyncMock(return_value={"status": "completed"})
        with patch("partyline_helper.screen_access_audit.audit_window"):
            await self.task._action(dict(action="invoke", element_id=self.rows["elements"][1]["id"],
                                        request_id="stale"))
            self.task.actions.perform.assert_not_awaited()
            await self.task._action(dict(action="invoke", element_id="toolbar", request_id="r"))
        self.task.actions.perform.assert_awaited_once()

    async def test_revoke_during_reload_prevents_session_setup_and_readback(self):
        def hook(m):
            if m["method"] == "Page.navigate":
                self.f.access.gate.revoked.set()
        await self.crash()
        self.f.socket.hook = hook
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual(result["status"], "unconfirmed")
        self.assertIn("consent revoked", result["error"])
        self.assertEqual(self.f.socket.attaches, 1)
        last = next(i for i, m in enumerate(self.f.socket.calls) if m["method"] == "Page.navigate")
        self.assertEqual(self.f.socket.calls[last + 1:], [])

    async def test_snapshot_metadata_and_recovery_after_revoke_are_safe(self):
        from tests.test_helper_window_snapshot import FakeBackend
        await self.crash()
        snapshots = self.f.shares.snapshots
        snapshots.backend = FakeBackend()
        calls = len(self.f.socket.calls)
        await snapshots.take(self.f.shares.grants["g"], {"agent": "agent"}, "r")
        self.assertEqual(len(self.f.socket.calls), calls)
        fields = self.f.session.send.await_args.kwargs
        self.assertEqual(fields["source"], "uia")
        self.assertEqual(fields["page_state"], "crashed")
        self.assertIn("reload", fields["recovery_hint"])
        self.f.access.gate.revoked.set()
        before = len(self.f.socket.calls)
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.f.socket.calls), before)

    async def test_crash_event_during_ax_read_falls_back_in_that_same_read(self):
        def hook(m):
            if m["method"] == "Accessibility.getFullAXTree":
                self.f.socket.event("Inspector.targetCrashed", session=self.page.session)
        self.f.socket.hook = hook
        result = await self.task.snapshot({}, {})
        self.assertEqual(result["source"], "uia")
        self.assertEqual(result["page_state"], "crashed")

    async def test_detached_crashed_reload_and_late_attach_revoke(self):
        await self.crash("Inspector.detached")
        result = await self.reload()
        self.assertEqual(result["status"], "completed")
        self.assertEqual((await self.f.read())["source"], "cdp")
        self.page = self.f.chrome.pages[self.f.access]["a"]
        await self.crash()
        def hook(m):
            if m["method"] == "Target.attachToTarget":
                self.f.access.gate.revoked.set()
        self.f.socket.hook = hook
        self.page.quiet.wait = AsyncMock(return_value="quiet")
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual(result["status"], "unconfirmed")
        await checkpoint()
        last_attach = max(i for i, m in enumerate(self.f.socket.calls)
                          if m["method"] == "Target.attachToTarget")
        self.assertTrue(all(m["method"] == "Target.detachFromTarget"
                            for m in self.f.socket.calls[last_attach + 1:]))

    async def test_missing_url_refuses_recovery_and_eval_while_crashed_has_hint(self):
        await self.crash()
        result = await self.f.chrome.action(self.f.access, dict(type="window_eval", expression="1"))
        self.assertEqual(result["status"], "failed")
        self.assertIn("reload", result["error"])
        self.page.url = ""
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual(result["status"], "failed")
        self.assertIn("last page URL", result["error"])
        self.assertFalse(any(m["method"] == "Page.navigate" for m in self.f.socket.calls))

    async def test_revoke_during_event_quiet_deadline_does_not_reattach(self):
        await self.crash()
        async def quiet():
            self.f.access.gate.revoked.set()
            return "quiet"
        self.page.quiet.wait = quiet
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(self.f.socket.attaches, 1)

    async def test_probe_exception_keeps_reads_on_uia(self):
        await self.crash()
        self.f.socket.crashed.clear()
        self.f.socket.event("Inspector.targetReloadedAfterCrash", session=self.page.session)
        await checkpoint()
        self.f.socket.eval_value = None
        response = self.f.socket.response
        def fail(m):
            if m["method"] == "Runtime.evaluate":
                return {"exceptionDetails": {"text": "failure"}}
            return response(m)
        self.f.socket.response = fail
        self.assertEqual((await self.task.snapshot({}, {}))["source"], "uia")
        self.assertEqual(self.page.page_state, "crashed")

    async def test_reinitialize_failure_preserves_crash_fallback_until_another_read(self):
        await self.crash()
        self.f.socket.crashed.clear()
        self.f.socket.event("Inspector.targetReloadedAfterCrash", session=self.page.session)
        await checkpoint()
        send = self.f.socket.send
        async def failing(raw):
            m = json.loads(raw)
            if m["method"] == "Inspector.enable":
                self.f.socket.calls.append(m)
                self.f.socket.queue.put_nowait(dict(id=m["id"], error={"message": "domain unavailable"}))
                return
            await send(raw)
        self.f.socket.send = failing
        result = await self.task.snapshot({}, {})
        self.assertEqual(result["source"], "uia")
        self.assertEqual(result["page_state"], "crashed")
        self.f.socket.send = send
        self.assertEqual((await self.task.snapshot({}, {}))["source"], "cdp")

    async def test_browser_target_information_keeps_url_and_clock_current(self):
        before = self.f.state.count
        self.f.socket.event("Target.targetInfoChanged", session=None,
                            targetInfo={"targetId": "a", "url": "https://example.test/next"})
        await checkpoint()
        self.assertEqual(self.page.url, "https://example.test/next")
        self.assertGreater(self.f.state.count, before)
        self.assertEqual(self.page.page_state, "alive")

    async def test_mapping_failure_during_crash_does_not_discard_recovery_session(self):
        await self.crash()
        self.f.window["title"] = "Aw, Snap! - Google Chrome"
        self.f.socket.rects[1]["left"] = 10000
        self.assertIsNone(await self.f.read())
        self.assertTrue(self.page.live)
        self.assertEqual(self.f.chrome.metadata(self.f.access)["page_state"], "crashed")
        result = await self.f.chrome.action(self.f.access,
            dict(action="invoke", element_id=self.rows["elements"][1]["id"]))
        self.assertEqual(result["status"], "failed")
        self.assertIn("reload", result["error"])
        self.f.socket.rects[1]["left"] = 10
        self.assertEqual((await self.reload())["status"], "completed")

    async def test_navigation_error_is_unconfirmed_and_never_retried(self):
        await self.crash()
        response = self.f.socket.response
        def fail(m):
            if m["method"] == "Page.navigate":
                return {"errorText": "private URL failure"}
            return response(m)
        self.f.socket.response = fail
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual(result["status"], "unconfirmed")
        self.assertNotIn("private", result["error"])
        self.assertEqual(sum(m["method"] == "Page.navigate" for m in self.f.socket.calls), 1)
        self.assertEqual(self.f.socket.attaches, 1)

    async def test_transport_classifies_lost_sessions_and_keeps_error_text_private(self):
        from partyline_helper.cdp_transport import CDPError, command_error
        error = command_error({"message": "Session with given id not found"})
        self.assertIsInstance(error, PageUnavailable)
        self.assertEqual(error.state, "detached")
        self.assertIsInstance(command_error({"message": "private page data"}), CDPError)
        self.assertNotIn("private", str(command_error({"message": "private page data"})))

    async def test_revoke_after_attach_reply_owns_and_stops_both_sessions(self):
        await self.crash()
        self.page.quiet.wait = AsyncMock(return_value="quiet")
        call = self.f.browser.call
        async def revoking(method, *args, **kwargs):
            if method == "Target.attachToTarget":
                arrived = kwargs["on_result"]
                def result(payload, abandoned):
                    arrived(payload, abandoned)
                    self.f.access.gate.revoked.set()
                    self.f.chrome.revoke(self.f.access)
                kwargs["on_result"] = result
            return await call(method, *args, **kwargs)
        self.f.browser.call = revoking
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual(result["status"], "unconfirmed")
        self.assertFalse(self.page.live)
        self.assertNotIn(self.page.event, self.f.browser.listeners)
        self.assertNotIn(self.f.access, self.f.chrome.pages)
        await checkpoint()
        self.assertFalse(self.f.browser.listeners)

    async def test_initial_attach_observes_crash_before_renderer_reads(self):
        self.f.chrome.revoke(self.f.access)
        self.f.socket.crashed.add("a")
        before = len(self.f.socket.calls)
        result = await self.task.snapshot({}, {})
        self.assertEqual(result["source"], "uia")
        self.assertEqual(result["page_state"], "crashed")
        self.assertFalse(self.f.socket.hung.is_set())
        self.assertFalse(any(m["method"] == "Accessibility.getFullAXTree"
                             for m in self.f.socket.calls[before:]))

    async def test_plain_screenshot_does_not_start_chrome_approval(self):
        from tests.test_helper_window_snapshot import FakeBackend
        fresh = Fixture()
        self.addAsyncCleanup(fresh.close)
        fresh.shares.snapshots.backend = FakeBackend()
        await fresh.shares.snapshots.take(fresh.shares.grants["g"], {"agent": "agent"}, "r")
        fresh.connector.assert_not_awaited()
        self.assertEqual(fresh.browser.state, "not_enabled")
        self.assertIsNone(fresh.chrome.connecting)
