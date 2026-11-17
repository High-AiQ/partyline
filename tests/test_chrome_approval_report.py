"""The helper reports which grants wait on Chrome's Allow prompt; its words explain setup and closure."""
import asyncio
from unittest import IsolatedAsyncioTestCase

from partyline.screen_chrome_state import ChromeState
from partyline_helper.cdp_transport import BrowserConnection, INSTRUCTION, SETUP
from partyline_helper.window_gone import closed_text, explain
from tests.cdp_fakes import Fixture, Socket
from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_event_state import EventState
from partyline_helper.window_shares import WindowSession
from tests.extension_fakes import fixture


async def reports(f):
    for _ in range(30):  # let the spawned sends run: loop turns, never a timer
        await asyncio.sleep(0)
    return [call.kwargs["grant_ids"] for call in f.session.send.await_args_list
            if call.args and call.args[0] == "chrome_approval"]


class ApprovalReportTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        self.prompt = asyncio.get_running_loop().create_future()

        async def connector(*args, **kwargs):
            return await self.prompt
        self.f.connector.side_effect = connector

    async def test_a_pending_prompt_is_reported_and_clears_on_approval(self):
        self.f.chrome.start(self.f.access)
        self.assertEqual([["g"]], await reports(self.f))
        self.prompt.set_result(self.f.socket)
        await self.f.chrome.connecting
        self.assertEqual([["g"], []], await reports(self.f))

    async def test_a_refused_prompt_clears_it(self):
        self.f.chrome.start(self.f.access)
        self.assertEqual([["g"]], await reports(self.f))
        self.prompt.set_exception(OSError("denied"))
        await self.f.chrome.connecting
        self.assertEqual([["g"], []], await reports(self.f))

    async def test_the_share_ending_clears_it(self):
        self.f.chrome.start(self.f.access)
        self.assertEqual([["g"]], await reports(self.f))
        del self.f.shares.grants["g"]
        self.f.chrome.revoke(self.f.access)
        self.assertEqual([["g"], []], await reports(self.f))
        self.prompt.cancel()

    async def test_a_grant_added_while_a_prompt_is_pending_is_reported_too(self):
        self.f.chrome.start(self.f.access)
        self.assertEqual([["g"]], await reports(self.f))
        late = WindowAccess(WindowSession(self.f.session, "h", lambda: None))
        late.grant = dict(self.f.window, hwnd=2)
        self.f.shares.grants["h"] = dict(access=late, title="Late", target=dict(line_name="line"),
                                       event_state=EventState())
        self.f.chrome.start(late)  # joins the connection already waiting: nothing starts, nothing is said
        self.f.shares.changed()  # the grant's activation
        self.assertEqual([["g"], ["g", "h"]], await reports(self.f))
        self.prompt.cancel()

    async def test_a_window_of_another_program_never_waits_for_chrome(self):
        self.f.access.grant["process"] = "editor.exe"
        self.f.chrome.report("awaiting_approval", "x")
        self.assertEqual([], await reports(self.f))


class FallbackApprovalTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f, self.peer = fixture()
        self.addAsyncCleanup(self.f.close)
        self.prompt = asyncio.get_running_loop().create_future()

        async def connector(*args, **kwargs):
            return await self.prompt
        self.f.chrome.fallback.factory = lambda changed: BrowserConnection(
            changed, discovery=lambda: "ws://fake", connector=connector)
        self.peer.refuse = {1: "other_extension_frame"}

    async def test_the_grant_moved_to_remote_debugging_waits_then_clears(self):
        await self.f.read()
        self.assertEqual([["g"]], await reports(self.f))
        remote = Socket()
        remote.urls = {"a": "https://example.test"}
        self.prompt.set_result(remote)
        await self.f.chrome.connecting
        self.assertEqual([["g"], []], await reports(self.f))

    async def test_the_extension_connecting_is_not_an_allow_prompt(self):
        self.f.browser.report("awaiting_approval", "")
        self.assertEqual([], await reports(self.f))
        self.prompt.cancel()


class SetupWordsTests(IsolatedAsyncioTestCase):
    async def test_missing_discovery_says_the_toggle_and_that_a_port_flag_is_not_used(self):
        browser = BrowserConnection(discovery=lambda: None)
        self.assertFalse(await browser.ensure())
        reason = browser.reason()
        self.assertIn(INSTRUCTION, reason)
        for text in ("chrome://inspect/#remote-debugging toggle", "normal Chrome", "--remote-debugging-port",
                     "separate profile", "not used"):
            self.assertIn(text, reason)
        self.assertIn(SETUP, reason)

    async def test_a_read_without_remote_debugging_carries_it_to_the_agent(self):
        f = Fixture()
        self.addAsyncCleanup(f.close)
        f.browser.discovery = lambda: None
        self.assertIsNone(await f.chrome.read(f.access, {}, dict(agent="agent", line_id="line")))
        self.assertIn("--remote-debugging-port", f.chrome.reasons[f.access])

    def test_the_tray_detail_stays_within_what_the_server_accepts(self):
        for detail in (INSTRUCTION, "Extension absent; remote debugging fallback. " + INSTRUCTION):
            ChromeState.model_validate({"state": "not_enabled", "detail": detail})


class ClosedWindowWordsTests(IsolatedAsyncioTestCase):
    async def test_a_chrome_window_that_closed_may_mean_chrome_restarted(self):
        f = Fixture()
        self.addAsyncCleanup(f.close)
        f.access.revoke("window closed")
        expected = "the shared window closed (Chrome may have restarted); share the window again"
        self.assertEqual(expected, closed_text("Chrome.exe"))
        for bare in ("consent revoked", "window read failed", "window closed"):
            self.assertEqual(expected, explain(f.access, bare))
        self.assertEqual("some other text", explain(f.access, "some other text"))

    async def test_a_real_revocation_keeps_its_own_wording(self):
        f = Fixture()
        self.addAsyncCleanup(f.close)
        f.access.revoke("revoked by the person")
        for bare in ("consent revoked", "window read failed"):
            self.assertEqual(bare, explain(f.access, bare))

    async def test_a_new_grant_after_a_close_is_not_called_closed(self):
        f = Fixture()
        self.addAsyncCleanup(f.close)
        window = f.access.grant
        f.access.revoke("window closed")
        f.access.grant = window
        self.assertEqual("consent revoked", explain(f.access, "consent revoked"))

    async def test_the_reload_after_a_close_and_the_failed_read_name_the_closed_window(self):
        f = Fixture()
        self.addAsyncCleanup(f.close)
        f.access.revoke("window closed")
        result = await f.chrome.action(f.access, dict(action="reload", element_id="page"))
        self.assertEqual(closed_text("chrome.exe"), explain(f.access, result["error"]))
