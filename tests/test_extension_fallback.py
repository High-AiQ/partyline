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
