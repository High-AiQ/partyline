"""Frame events change observations; only main-document replacement invalidates page identities."""
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from tests.cdp_fakes import Fixture
from tests.screen_helper_fakes import checkpoint


class Navigation(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        self.rows = await self.f.read()
        self.page = self.f.chrome.pages[self.f.access]["a"]
        self.page.quiet.wait = AsyncMock(return_value="quiet")
        self.link, self.select = [row["id"] for row in self.rows["elements"][1:]]
        self.f.socket.states[2]["aria_disabled"] = False

    def emit(self, method, **params):
        self.f.socket.event(method, **params)

    def on_mouse(self, callback, kind="mouseReleased"):
        def hook(message):
            if message["method"] == "Input.dispatchMouseEvent" and message["params"]["type"] == kind:
                callback()
        self.f.socket.hook = hook

    async def invoke(self):
        return await self.f.chrome.action(self.f.access, dict(action="invoke", element_id=self.link))

    async def test_iframe_navigation_and_removal_keep_clicks_and_page_ids_valid(self):
        for method, params in (("Page.frameNavigated", {"frame": {"id": "ad", "parentId": "main"}}),
                               ("Page.frameDetached", {"frameId": "ad", "reason": "remove"})):
            with self.subTest(method=method):
                before = self.f.state.count
                self.on_mouse(lambda method=method, params=params: self.emit(method, **params))
                result = await self.invoke()
                self.assertEqual(result["status"], "completed")
                self.assertNotIn("navigated", result)
                self.assertGreater(self.f.state.count, before)
                self.assertEqual(self.page.epoch, 0)
                self.assertIn(self.link, self.page.nodes)
                self.assertIn("live", await self.f.read(inspect=self.link))
                refreshed = await self.f.read()
                self.assertEqual(refreshed["elements"][1]["id"], self.link)

    async def test_iframe_events_during_popup_selection_do_not_interrupt_or_leave_it_open(self):
        def hook(message):
            if message["method"] == "Input.dispatchKeyEvent":
                self.emit("Page.frameNavigated", frame={"id": "ad", "parentId": "main"})
                self.emit("Page.frameDetached", frameId="ad", reason="swap")
        self.f.socket.hook = hook
        result = await self.f.chrome.action(self.f.access,
            dict(action="select", element_id=self.select, value="New"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["trusted_change_events"], 1)
        self.assertEqual(result["selection_mode"], "keyboard_popup")
        self.assertFalse(self.f.socket.native_select.open)
        self.assertFalse(self.f.socket.native_select.watches)
        self.assertIn(self.select, self.page.nodes)

    async def test_main_navigation_after_link_release_completes_without_observing_old_element(self):
        self.on_mouse(lambda: self.emit("Page.frameNavigated", frame={"id": "main"}))
        result = await self.invoke()
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["navigated"])
        self.assertEqual(result["settle"], "changing")
        self.assertNotIn("element", result)
        self.assertFalse(self.page.nodes)
        release = next(i for i, m in enumerate(self.f.socket.calls)
                       if m["method"] == "Input.dispatchMouseEvent" and
                       m["params"]["type"] == "mouseReleased")
        self.assertEqual(self.f.socket.calls[release + 1:], [])

    async def test_main_navigation_during_settle_is_also_a_completed_link_invoke(self):
        async def quiet():
            self.emit("Page.frameNavigated", frame={"id": "main"})
            await checkpoint()
            return "quiet"
        self.page.quiet.wait = quiet
        result = await self.invoke()
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["navigated"])

    async def test_navigation_before_release_does_not_finish_click_in_another_document(self):
        self.on_mouse(lambda: self.emit("Page.frameNavigated", frame={"id": "main"}), "mousePressed")
        result = await self.invoke()
        self.assertEqual(result["status"], "unconfirmed")
        self.assertFalse(any(m["method"] == "Input.dispatchMouseEvent" and
                             m["params"]["type"] == "mouseReleased" for m in self.f.socket.calls))

    async def test_document_replacement_alone_does_not_claim_navigation_success(self):
        self.on_mouse(lambda: self.emit("DOM.documentUpdated"))
        result = await self.invoke()
        self.assertEqual(result["status"], "unconfirmed")
        self.assertFalse(self.page.nodes)

    async def test_revocation_overrides_even_a_confirmed_main_navigation(self):
        def revoke():
            self.emit("Page.frameNavigated", frame={"id": "main"})
            self.f.access.gate.revoked.set()
        self.on_mouse(revoke)
        result = await self.invoke()
        self.assertEqual(result["status"], "unconfirmed")
        self.assertNotIn("navigated", result)
        self.assertIn("consent revoked", result["error"])
