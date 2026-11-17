"""A grant Chrome will not let the extension debug moves to remote debugging; others stay on the extension."""
import asyncio
import unittest
from unittest.mock import AsyncMock

from partyline_helper.cdp_transport import BrowserConnection
from tests.cdp_fakes import Socket
from tests.extension_fakes import fixture


class FallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f, self.peer = fixture()
        self.addAsyncCleanup(self.f.close)
        self.remote_socket = Socket()
        self.remote_socket.urls = {"a": "https://example.test", "b": "https://background.test"}
        self.made = []
        self.discoverable = True

        def factory(changed):
            remote = BrowserConnection(changed, discovery=lambda: "ws://fake" if self.discoverable else None,
                                       connector=AsyncMock(return_value=self.remote_socket))
            self.made.append(remote)
            return remote
        self.f.chrome.fallback.factory = factory

    async def read_after_prompt(self):
        await self.f.read()
        if self.f.chrome.connecting:
            await self.f.chrome.connecting
        return await self.f.read()

    async def detach_attached_page(self, refusal):
        result = await self.f.read()
        self.assertEqual((result["source"], result["transport"]), ("cdp", "extension"))
        page = self.f.chrome.pages[self.f.access][self.f.chrome.selected[self.f.access]]
        page.page_state = "detached"
        self.peer.refuse = {int(page.target): refusal}
        return page

    async def test_other_extension_frame_moves_only_this_grant_to_remote_debugging(self):
        self.peer.refuse = {1: "other_extension_frame"}
        await self.f.browser.ensure()
        tray = self.f.session.status.chrome
        self.assertEqual(tray, "Chrome: extension connected")
        first = await self.f.read()
        self.assertIsNone(first)  # UIA meanwhile: the Allow prompt is pending
        self.assertIn(self.f.access, self.f.chrome.fallback.grants)
        self.assertTrue(self.peer.revoked)  # the extension drops its hold on this grant
        self.assertIn("Approve the remote debugging connection", self.f.chrome.reasons[self.f.access])
        await self.f.chrome.connecting
        result = await self.f.read()
        self.assertEqual((result["source"], result["transport"]), ("cdp", "remote_debugging"))
        self.assertEqual(self.f.session.status.chrome, tray)  # the tray row still describes the extension
        self.assertEqual(len(self.made), 1)
        self.assertEqual(sum(m["method"] == "Target.attachToTarget" for m in self.peer.calls), 1)

    async def test_an_already_attached_tab_falls_back_the_same_way(self):
        self.peer.refuse = {1: "debugger_already_attached"}
        result = await self.read_after_prompt()
        self.assertEqual((result["source"], result["transport"]), ("cdp", "remote_debugging"))

    async def test_detached_page_refusal_moves_the_grant_and_reads_the_same_tab_remotely(self):
        page = await self.detach_attached_page("other_extension_frame")
        self.f.access.grant["target_id"] = page.target
        result = await self.f.read()
        self.assertIsNone(result)
        self.assertIn(self.f.access, self.f.chrome.fallback.grants)
        self.assertTrue(self.peer.revoked)
        self.assertIn("Approve the remote debugging connection", self.f.chrome.reasons[self.f.access])
        await self.f.chrome.connecting
        result = await self.f.read()
        self.assertEqual((result["source"], result["transport"]), ("cdp", "remote_debugging"))
        self.assertEqual(self.f.chrome.selected[self.f.access], "a")
        self.assertEqual(self.remote_attaches(), ["a"])

    async def test_detached_page_debugger_refusal_also_moves_to_remote_debugging(self):
        page = await self.detach_attached_page("debugger_already_attached")
        self.f.access.grant["target_id"] = page.target
        self.assertIsNone(await self.f.read())
        await self.f.chrome.connecting
        result = await self.f.read()
        self.assertEqual((result["source"], result["transport"]), ("cdp", "remote_debugging"))

    async def test_detached_page_reload_moves_the_grant_and_reports_pending_approval(self):
        page = await self.detach_attached_page("other_extension_frame")
        self.f.access.grant["target_id"] = page.target
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual(result["status"], "failed")
        self.assertIn("Approve the remote debugging connection", result["error"])
        self.assertNotIn("other_extension_frame", result["error"])
        self.assertIn(self.f.access, self.f.chrome.fallback.grants)
        self.assertTrue(self.peer.revoked)
        await self.f.chrome.connecting
        result = await self.f.read()
        self.assertEqual((result["source"], result["transport"]), ("cdp", "remote_debugging"))
        self.assertEqual(self.f.chrome.selected[self.f.access], "a")

    async def test_reload_already_dispatched_reports_unconfirmed_and_does_not_ask_to_reload_again(self):
        result = await self.f.read()
        self.assertEqual((result["source"], result["transport"]), ("cdp", "extension"))
        page = self.f.chrome.pages[self.f.access][self.f.chrome.selected[self.f.access]]
        page.quiet.wait = AsyncMock(return_value="quiet")
        call = self.f.browser.call

        async def refuse_reattach_after_reload(method, *args, **kwargs):
            result = await call(method, *args, **kwargs)
            if method == "Page.reload":
                self.peer.refuse[int(page.target)] = "other_extension_frame"
            return result

        self.f.browser.call = refuse_reattach_after_reload
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual(result["status"], "unconfirmed")
        self.assertIn("Approve the remote debugging connection", result["error"])
        self.assertIn("read again after Chrome allows", result["error"])
        self.assertNotIn("call reload again", result["error"])
        self.assertEqual(sum(m["method"] == "Page.reload" for m in self.peer.calls), 1)
        self.assertIn(self.f.access, self.f.chrome.fallback.grants)

    async def test_detached_page_with_remote_debugging_off_stays_on_uia_with_actionable_reason(self):
        await self.detach_attached_page("other_extension_frame")
        self.discoverable = False
        self.assertIsNone(await self.f.read())
        reason = self.f.chrome.reasons[self.f.access]
        self.assertIn("another extension's frame is in it", reason)
        self.assertIn("chrome://inspect/#remote-debugging", reason)
        self.assertTrue(reason.endswith("; using UIA"))
        self.assertNotIn(self.f.access, self.f.chrome.fallback.grants)
        self.assertEqual(self.f.chrome.sources[self.f.access], "uia")

    async def test_detached_page_reload_with_remote_debugging_off_returns_actionable_reason(self):
        await self.detach_attached_page("other_extension_frame")
        self.discoverable = False
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual(result["status"], "failed")
        self.assertIn("another extension's frame is in it", result["error"])
        self.assertIn("chrome://inspect/#remote-debugging", result["error"])
        self.assertNotIn("other_extension_frame", result["error"])
        self.assertNotIn(self.f.access, self.f.chrome.fallback.grants)

    async def test_detached_page_with_other_refusal_does_not_fall_back(self):
        await self.detach_attached_page("domain_refused")
        self.assertIsNone(await self.f.read())
        self.assertEqual(self.f.chrome.fallback.grants, set())
        self.assertIsNone(self.f.chrome.fallback.remote)
        self.assertEqual(self.f.chrome.sources[self.f.access], "uia")

    async def test_without_remote_debugging_the_reason_says_what_to_do(self):
        self.discoverable = False
        self.peer.refuse = {1: "other_extension_frame"}
        await self.f.read()
        reason = self.f.chrome.reasons[self.f.access]
        self.assertIn("another extension's frame is in it", reason)
        self.assertIn("chrome://inspect/#remote-debugging", reason)
        self.assertIn("disable the extension that injects it", reason)
        self.assertTrue(reason.endswith("; using UIA"))
        self.assertEqual((self.f.chrome.fallback.remote, self.f.chrome.fallback.grants), (None, set()))
        self.peer.refuse = {1: "debugger_already_attached"}
        await self.f.read()
        self.assertIn("DevTools or another debugging extension", self.f.chrome.reasons[self.f.access])

    async def test_other_refusals_never_fall_back_and_keep_their_code(self):
        self.peer.refuse = {1: "domain_refused"}
        await self.f.read()
        self.assertEqual((self.f.chrome.fallback.remote, self.f.chrome.fallback.grants), (None, set()))
        self.assertIn("domain_refused", self.f.chrome.reasons[self.f.access])

    async def test_reload_reattach_refusal_without_remote_debugging_gives_actionable_reason(self):
        from partyline_helper.chrome_fallback import REASONS
        await self.f.read()
        page = next(iter(self.f.chrome.pages[self.f.access].values()))
        page.quiet.wait = AsyncMock(return_value="quiet")
        self.discoverable = False
        self.peer.refuse = {1: "other_extension_frame"}
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual("unconfirmed", result["status"])  # reload ran before reattach was refused
        self.assertEqual(REASONS["other_extension_frame"], result["error"])
        self.assertEqual((None, set()), (self.f.chrome.fallback.remote, self.f.chrome.fallback.grants))

    async def test_detached_recovery_attach_refusal_has_the_same_actionable_reason(self):
        from partyline_helper.chrome_fallback import REASONS
        await self.f.read()
        page = next(iter(self.f.chrome.pages[self.f.access].values()))
        page.page_state = "detached"
        self.discoverable = False
        self.peer.refuse = {1: "other_extension_frame"}
        result = await self.f.chrome.action(self.f.access, dict(action="reload", element_id="page"))
        self.assertEqual("failed", result["status"])
        self.assertEqual(REASONS["other_extension_frame"], result["error"])

    async def test_revoking_the_grant_closes_the_remote_connection(self):
        self.peer.refuse = {1: "other_extension_frame"}
        await self.read_after_prompt()
        self.f.chrome.revoke(self.f.access)
        self.assertEqual(self.f.chrome.fallback.grants, set())
        self.assertIsNone(self.f.chrome.fallback.remote)
        await asyncio.gather(*list(self.f.shares.tasks))
        self.assertTrue(self.made[0].closed)
        self.assertTrue(self.remote_socket.closed)

    async def test_a_picked_tab_is_found_again_by_url_and_title_in_the_remote_namespace(self):
        self.f.access.grant["target_id"] = "1"  # the extension's tab id for the picked tab
        self.peer.refuse = {1: "other_extension_frame"}
        result = await self.read_after_prompt()
        self.assertEqual((result["source"], result["transport"]), ("cdp", "remote_debugging"))
        self.assertEqual(self.f.chrome.selected[self.f.access], "a")  # the remote id of that same tab

    async def test_a_picked_tab_that_is_not_found_exactly_once_selects_nothing(self):
        self.f.access.grant["target_id"] = "1"
        self.peer.refuse = {1: "other_extension_frame"}
        self.remote_socket.urls["a"] = "https://moved.test"  # the picked tab's page is no longer there
        self.assertIsNone(await self.read_after_prompt())  # never falls back to some other active tab
        self.assertEqual(self.f.chrome.pages.get(self.f.access), {})
        self.assertNotIn("Target.attachToTarget", [m["method"] for m in self.remote_socket.calls])
        self.assertIn("pick a tab again", self.f.chrome.reasons[self.f.access])

    async def test_an_ambiguous_match_at_bind_time_selects_nothing(self):
        self.f.access.grant["target_id"] = "1"
        self.peer.refuse = {1: "other_extension_frame"}
        self.remote_socket.urls["b"], self.remote_socket.titles["b"] = "https://example.test", "Lab"
        self.assertIsNone(await self.read_after_prompt())  # two tabs look like the picked one
        self.assertEqual(self.remote_attaches(), [])
        self.assertIsNone(self.f.chrome.fallback.bound[self.f.access])
        self.assertIn("pick a tab again", self.f.chrome.reasons[self.f.access])

    async def test_a_late_attach_reply_is_cleaned_up_on_the_connection_that_sent_it(self):
        self.peer.refuse = {1: "other_extension_frame"}
        await self.f.read()
        await self.f.chrome.connecting
        other = object()
        self.f.chrome.fallback.grants.add(other)  # a second fallback grant keeps the remote connection open

        def revoke_during_attach(message):
            if message["method"] == "Target.attachToTarget":
                self.f.access.gate.revoked.set()
                self.f.chrome.revoke(self.f.access)
        self.remote_socket.hook = revoke_during_attach
        await self.f.read()
        await asyncio.gather(*list(self.f.shares.tasks))
        detached = [m for m in self.remote_socket.calls if m["method"] == "Target.detachFromTarget"]
        self.assertEqual([m["params"]["sessionId"] for m in detached], ["a"])
        self.assertFalse([m for m in self.peer.calls if m["method"] == "Target.detachFromTarget"])

    async def bound_to_the_picked_tab(self):
        self.f.access.grant["target_id"] = "1"
        self.peer.refuse = {1: "other_extension_frame"}
        await self.read_after_prompt()
        self.assertEqual(self.f.chrome.selected[self.f.access], "a")

    def tab_b_takes_over_the_picked_tabs_content(self):
        sock = self.remote_socket
        sock.urls["b"], sock.titles["b"] = "https://example.test", "Lab"
        sock.urls["a"], sock.titles["a"] = "https://moved.test", "Moved"

    def remote_attaches(self):
        calls = self.remote_socket.calls
        return [m["params"]["targetId"] for m in calls if m["method"] == "Target.attachToTarget"]

    async def test_the_bound_tab_stays_the_grants_tab_after_it_navigates_and_a_lookalike_appears(self):
        await self.bound_to_the_picked_tab()
        self.tab_b_takes_over_the_picked_tabs_content()
        result = await self.f.read()
        self.assertEqual(result["source"], "cdp")
        self.assertEqual(self.f.chrome.selected[self.f.access], "a")
        self.assertEqual(self.remote_attaches(), ["a"])  # the look-alike tab is never touched

    async def test_a_closed_bound_tab_fails_closed_instead_of_moving_to_a_look_alike(self):
        await self.bound_to_the_picked_tab()
        self.tab_b_takes_over_the_picked_tabs_content()
        del self.remote_socket.windows["a"]  # the picked tab closed
        self.f.chrome.pages.pop(self.f.access).clear()
        self.assertIsNone(await self.f.read())
        self.assertEqual(self.remote_attaches(), ["a"])
        self.assertIn("The picked tab closed; pick a tab again", self.f.chrome.reasons[self.f.access])
        self.assertIsNone(await self.f.read())  # still nothing: never re-matched by content
        self.assertEqual(self.remote_attaches(), ["a"])

    async def navigate_remote_tab(self):
        frame = {"id": "root", "url": "https://example.test/next"}
        self.remote_socket.event("Page.frameNavigated", session="a", frame=frame)
        await self.made[0].call("Browser.getVersion")  # the event is queued before this reply

    async def test_a_refused_grant_reports_why_and_returns_to_the_extension_on_navigation(self):
        self.peer.refuse = {1: "other_extension_frame"}
        result = await self.read_after_prompt()
        self.assertEqual((result["transport"], result["fallback_reason"]), ("remote_debugging",
                                                                            "other_extension_frame"))
        self.peer.refuse = {}  # the page no longer hosts the other extension's frame
        await self.navigate_remote_tab()
        result = await self.f.read()
        self.assertEqual((result["source"], result["transport"]), ("cdp", "extension"))
        self.assertNotIn("fallback_reason", result)
        self.assertEqual(self.f.chrome.fallback.grants, set())
        self.assertTrue(self.made[0].closed or self.made[0].socket is None)  # nothing needs remote debugging
        self.assertIsNone(self.f.chrome.fallback.remote)

    async def test_a_repeated_refusal_stays_on_remote_debugging_without_asking_again(self):
        self.peer.refuse = {1: "other_extension_frame"}
        await self.read_after_prompt()
        await self.navigate_remote_tab()
        result = await self.f.read()  # the extension refuses again: the open connection serves the grant
        self.assertEqual((result["transport"], result["fallback_reason"]), ("remote_debugging",
                                                                            "other_extension_frame"))
        self.assertEqual(len(self.made), 1)
        self.assertEqual(self.made[0].connector.await_count, 1)  # no second Allow prompt
        self.assertIn(self.f.access, self.f.chrome.fallback.grants)

    async def test_without_a_navigation_a_refused_grant_does_not_retry_the_extension(self):
        self.peer.refuse = {1: "other_extension_frame"}
        await self.read_after_prompt()
        self.peer.refuse = {}
        result = await self.f.read()
        self.assertEqual(result["transport"], "remote_debugging")
