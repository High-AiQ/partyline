"""Selected-tab counters and single-commit popup selection use deterministic protocol events."""
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from partyline_helper.cdp_recipes import STATE
from tests.cdp_fakes import Fixture
from tests.screen_helper_fakes import checkpoint
from tests.windows_uia_patterns import foreground_observation


class ActiveSelect(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        await self.f.read()

    @patch("partyline_helper.cdp_page.PAGE_CAP", 16)
    async def test_background_tab_cannot_break_selected_tab_continuation(self):
        old = self.f.chrome.pages[self.f.access]["a"]
        self.f.socket.visible.update(a=False, b=True)
        self.f.window["title"] = "Background - Google Chrome"
        self.f.socket.nodes = [dict(nodeId=str(n), role={"value": "StaticText"}, name={"value": "row"})
                               for n in range(17)]
        first = await self.f.read()
        counter = self.f.state.count
        self.f.socket.event(session="a")
        self.f.socket.event("Runtime.bindingCalled", session="a", name="__partylineChange", payload="")
        await checkpoint()
        self.assertEqual(self.f.state.count, counter)
        self.assertFalse(old.live)
        self.assertEqual(set(self.f.chrome.pages[self.f.access]), {"b"})
        self.assertTrue(any(m["method"] == "Target.detachFromTarget" and m["params"]["sessionId"] == "a"
                            for m in self.f.socket.calls))
        rest = await self.f.read(cursor=first["next_cursor"])
        self.assertEqual(len(rest["elements"]), 1)
        self.assertEqual(rest["snapshot_id"], first["snapshot_id"])

    async def test_background_event_during_selected_action_keeps_settle_quiet(self):
        self.f.socket.visible.update(a=False, b=True)
        self.f.window["title"] = "Background - Google Chrome"
        rows = await self.f.read()
        page = self.f.chrome.pages[self.f.access]["b"]
        after_quiet = False
        async def quiet():
            nonlocal after_quiet
            after_quiet = True
            return "quiet"
        page.quiet.wait = quiet
        def hook(message):
            if (after_quiet and message["method"] == "Runtime.callFunctionOn"
                    and message["params"]["functionDeclaration"] == STATE):
                self.f.socket.event(session="a")
        self.f.socket.hook = hook
        ident = next(row["id"] for row in rows["elements"] if row["control_type"] == "ComboBox")
        result = await self.f.chrome.action(self.f.access,
                                             dict(action="select", element_id=ident, value="New"))
        self.assertEqual(result["settle"], "quiet")

    async def select(self, current, target):
        self.f.socket.options = [dict(label=c, value=c) for c in "ABCDE"]
        self.f.socket.states[3].update(selected_index=current, value="ABCDE"[current])
        rows = await self.f.read()
        page = self.f.chrome.pages[self.f.access]["a"]
        page.quiet.wait = AsyncMock(return_value="quiet")
        ident = next(row["id"] for row in rows["elements"] if row["control_type"] == "ComboBox")
        return await self.f.chrome.action(self.f.access,
            dict(action="select", element_id=ident, value=target))

    async def test_popup_navigates_from_current_and_commits_only_target(self):
        result = await self.select(1, "D")
        self.assertEqual(result["selection_mode"], "keyboard_popup")
        self.assertEqual(result["trusted_change_events"], 1)
        self.assertEqual(self.f.socket.native_select.committed_values, ["D"])
        keys = [m["params"] for m in self.f.socket.calls if m["method"] == "Input.dispatchKeyEvent"
                and m["params"]["type"] == "keyDown"]
        self.assertEqual([m["key"] for m in keys], ["ArrowDown", "ArrowDown", "ArrowDown", "Enter"])
        self.assertEqual([m["modifiers"] for m in keys], [1, 0, 0, 0])

    async def test_unsupported_popup_falls_back_one_step_from_current(self):
        self.f.socket.native_select.mode = "unsupported"
        result = await self.select(1, "C")
        self.assertEqual(result["selection_mode"], "keyboard_steps")
        self.assertEqual(result["trusted_change_events"], 1)
        self.assertEqual(self.f.socket.native_select.committed_values, ["C"])

    async def test_popup_ignoring_keys_is_cancelled_before_current_option_fallback(self):
        self.f.socket.native_select.mode = "ignored"
        result = await self.select(2, "B")
        self.assertEqual(result["selection_mode"], "keyboard_steps")
        self.assertEqual(result["trusted_change_events"], 1)
        self.assertEqual(self.f.socket.native_select.committed_values, ["B"])
        self.assertFalse(self.f.socket.native_select.open)
        self.assertFalse(self.f.socket.native_select.watches)

    async def test_popup_ignoring_escape_is_blurred_before_fallback(self):
        self.f.socket.native_select.mode = "ignored_all"
        result = await self.select(1, "C")
        self.assertEqual(result["selection_mode"], "keyboard_steps")
        self.assertEqual(self.f.socket.native_select.committed_values, ["C"])
        self.assertFalse(self.f.socket.native_select.open)

    async def test_closed_or_unfocused_picker_never_sends_enter(self):
        for mode in ("closed", "focus_stolen"):
            with self.subTest(mode=mode):
                self.f.socket.native_select.mode = mode
                result = await self.select(1, "C")
                self.assertEqual("unconfirmed", result["status"])
                self.assertIn("before Enter", result["error"])
                self.assertEqual([], self.f.socket.native_select.committed_values)
                self.assertFalse(any(m["method"] == "Input.dispatchKeyEvent"
                                     and m["params"]["key"] == "Enter" for m in self.f.socket.calls))
                self.f.socket.calls.clear()
                self.f.socket.input_events.clear()

    async def test_premature_commit_cancels_picker_and_removes_event_watch(self):
        self.f.socket.native_select.mode = "premature"
        result = await self.select(1, "C")
        self.assertEqual(result["status"], "unconfirmed")
        self.assertIn("committed before Enter", result["error"])
        self.assertFalse(self.f.socket.native_select.open)
        self.assertFalse(self.f.socket.native_select.watches)
        self.assertFalse(any(m["method"] == "Input.dispatchKeyEvent" and m["params"]["key"] == "Enter"
                             for m in self.f.socket.calls))

    async def test_navigation_on_change_stops_further_keys_in_another_document(self):
        self.f.socket.native_select.mode = "unsupported"
        self.f.socket.native_select.navigate_on_change = True
        result = await self.select(1, "D")
        self.assertEqual(result["status"], "unconfirmed")
        self.assertIn("document changed", result["error"])
        self.assertEqual(self.f.socket.native_select.committed_values, ["C"])


class NativeForegroundContract(TestCase):
    def test_native_fixture_accepts_transient_activation_followed_by_restoration(self):
        answer = dict(foreground_changed=True, target_came_forward=True, foreground_restored=True)
        foreground_observation(self, answer, 99, 99, 1)
        with self.assertRaises(AssertionError):
            foreground_observation(self, answer, 99, 1, 1)
        unchanged = dict(foreground_changed=False, target_came_forward=False, foreground_restored=False)
        foreground_observation(self, unchanged, 99, 99, 1)
