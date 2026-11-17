"""A closed shared window is named on the real routes; a revocation or another line keeps the generic one."""
import unittest

from tests.window_grant_fixtures import WindowGrantFixture

CLOSED = "the shared window closed (Chrome may have restarted); share the window again"


class ClosedWindowRouteTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def end(self, reason, grant_id="g1"):
        await self.hub.window_grants.from_helper(
            self.device, {"type": "window_revoked", "grant_id": grant_id, "reason": reason})

    async def test_a_read_after_the_window_closed_says_so_with_or_without_naming_it(self):
        await self.grant("a", "Shared page", process="chrome.exe")
        await self.end("window closed")
        for window in (None, "g1", "Shared page"):
            with self.subTest(window=window):
                response = await self.read("a", window)
                self.assertEqual((403, CLOSED), (response.status_code, response.json()["detail"]))

    async def test_an_action_after_the_window_closed_says_so_too(self):
        await self.grant("a", "Shared page", process="chrome.exe")
        await self.end("window closed")
        response = await self.act("a", "g1")
        self.assertEqual((403, CLOSED), (response.status_code, response.json()["detail"]))

    async def test_a_program_that_is_not_chrome_gets_no_restart_hint(self):
        await self.grant("a")
        await self.end("window closed")
        self.assertEqual("the shared window closed; share the window again",
                         (await self.read("a")).json()["detail"])

    async def test_a_real_revocation_keeps_the_generic_refusal(self):
        await self.grant("a", process="chrome.exe")
        await self.end("revoked by the person")
        detail = (await self.read("a")).json()["detail"]
        self.assertIn("no window is shared with this line", detail)
        self.assertNotIn("closed", detail)

    async def test_a_later_revocation_on_the_line_replaces_the_closed_report(self):
        await self.grant("a", process="chrome.exe")
        await self.end("window closed")
        await self.grant("a", "Other", grant_id="g2", hwnd=11)
        await self.end("revoked by the person", "g2")
        self.assertIn("no window is shared", (await self.read("a")).json()["detail"])

    async def test_another_line_is_never_told_about_the_closed_window(self):
        await self.grant("a", process="chrome.exe")
        await self.end("window closed")
        self.assertNotIn("closed", (await self.read("b")).json()["detail"])
        self.assertNotIn("closed", (await self.client.post(
            "/api/conversations/beta/screen-elements", headers=self.machine("b"),
            params={"window": "g1"})).json()["detail"])


class InFlightClosureTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def reload(self, reason):
        await self.grant("a", "Shared page", process="chrome.exe")
        self.device["chrome_dom"] = 4  # a helper that can reload
        original = self.device["socket"].send_json

        async def helper(message):
            if message["type"] == "window_element_action":
                await self.hub.window_grants.from_helper(self.device, {
                    "type": "window_revoked", "grant_id": "g1", "reason": reason})
                self.hub.elements.receive(self.device, {
                    "request_id": message["request_id"], "status": "failed", "error": CLOSED})
            else:
                await original(message)
        self.device["socket"].send_json = helper
        response = await self.client.post(
            "/api/conversations/alpha/screen-control/element-action", headers=self.machine("a"),
            json={"window": "g1", "element_id": "page", "action": "reload"})
        return response.json()

    async def test_a_window_that_closes_during_a_reload_keeps_its_explanation_and_the_retry_advice(self):
        result = await self.reload("window closed")
        self.assertEqual((True, "failed", CLOSED), (result["grant_ended"], result["status"], result["error"]))
        self.assertIn("Do not retry automatically", result["note"])
        self.assertIn(CLOSED, result["note"])

    async def test_a_revocation_during_a_reload_stays_the_generic_ended_note(self):
        result = await self.reload("revoked by the person")
        self.assertNotIn("error", result)
        self.assertNotIn("closed", result["note"])
