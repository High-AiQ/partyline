"""An extension entry left under a grant from before an update must not strand a new grant."""
import unittest

from partyline_helper.cdp_transport import CDPError, ExtensionRefused, command_error
from partyline_helper.cdp_transport import PageUnavailable
from tests.extension_fakes import fixture


class StaleHoldTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f, self.peer = fixture()
        self.addAsyncCleanup(self.f.close)

    def attaches(self):
        return [m for m in self.peer.calls if m["method"] == "Target.attachToTarget"]

    async def test_new_grant_reads_the_tab_an_old_grant_still_holds_after_one_retry(self):
        self.peer.stale = {1: "old-grant"}
        result = await self.f.read()
        self.assertEqual(result["source"], "cdp")
        self.assertEqual(len(self.attaches()), 2)  # refused, then released and retried exactly once
        release = self.peer.released[0]
        self.assertEqual(release["tabs"], [1])
        self.assertEqual(release["live"], ["g"])  # only this helper's own live grant is spared
        self.assertEqual(self.peer.stale, {})

    async def test_a_live_grants_tab_is_never_released_and_the_code_is_reported_after_one_retry(self):
        self.peer.stale = {1: "g"}  # the extension holds this tab for a grant the helper still has
        await self.f.browser.ensure()
        self.assertIsNone(await self.f.chrome.page(self.f.access))
        self.assertEqual(len(self.attaches()), 2)
        self.assertEqual(self.peer.stale, {1: "g"})
        reason = self.f.chrome.reasons[self.f.access]
        self.assertIn("Chrome extension refused Target.attachToTarget: tab_owned_by_other_grant", reason)

    async def test_reload_takes_the_same_recovery_path_and_names_the_code_when_it_still_fails(self):
        await self.f.browser.ensure()
        self.peer.stale = {1: "old-grant"}
        result = await self.f.chrome.action(self.f.access, {"action": "reload", "line_id": "line"})
        self.assertNotIn("needs a mapped", result.get("error", ""))
        self.assertEqual(len(self.peer.released), 1)
        self.peer.stale = {1: "g"}
        self.f.chrome.pages.clear()
        result = await self.f.chrome.action(self.f.access, {"action": "reload", "line_id": "line"})
        self.assertEqual(result["status"], "failed")
        self.assertIn("tab_owned_by_other_grant", result["error"])

    def test_refusal_codes_are_fixed_text_with_the_method_and_never_page_derived(self):
        error = command_error({"message": "https://private.example/path", "code": "domain_refused"},
                              "Accessibility.getFullAXTree")
        self.assertIsInstance(error, ExtensionRefused)
        self.assertEqual(str(error), "Chrome extension refused Accessibility.getFullAXTree: domain_refused")
        self.assertEqual(str(command_error({"code": "revoked"}, "bad method <script>")),
                         "Chrome extension refused: revoked")
        self.assertIsInstance(command_error({"code": "debugger_detached"}, "DOM.enable"), PageUnavailable)
        for code in ("nonsense", 7, None):
            error = command_error({"message": "private page data", "code": code}, "DOM.enable")
            self.assertEqual(str(error), "Chrome rejected the CDP command")
            self.assertNotIsInstance(error, ExtensionRefused)
        self.assertIsInstance(error, CDPError)
