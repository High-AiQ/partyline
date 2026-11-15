"""Scroll, drag, type and key in the helper: both routes, the click rules, passwords and combos, faked."""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from partyline_helper import point_cdp_ops, point_cursor, point_keys, point_win32
from partyline_helper.cdp_transport import CDPError
from partyline_helper.point_consent import COOLDOWN
from partyline_helper.point_ops import NEEDS_CLICK, arguments, path, which
from partyline_helper.uia_window_list import HARD_FLOOR
from partyline_helper.window_click import FLOOR, GONE, LATE, STALE
from tests.test_helper_window_click import ClickFixture, FakePage, FakePointer, areas


class Pointer(FakePointer):
    """The cursor route's keyboard and wheel as a fake that records what the person's computer would get."""

    def __init__(self):
        super().__init__()
        self.password, self.covered, self.typed, self.keys = False, set(), [], []
        self.wheel, self.drag, self.partial = [], [], None
        self.tab_into_password = False  # a Tab moves the focus into a password field

    def window_at(self, x, y):
        return 99 if (x, y) in self.covered else super().window_at(x, y)

    def send_wheel(self, point, dx, dy):
        self.calls.append(("wheel", tuple(point), dx, dy))
        self.wheel.append((tuple(point), dx, dy))
        self.cursor_at = tuple(point)
        return self.partial or (3, 3)

    def send_drag(self, points):
        self.calls.append(("drag", [tuple(p) for p in points]))
        self.drag.append([tuple(p) for p in points])
        self.cursor_at = tuple(points[-1])
        return self.partial or (len(points) + 2, len(points) + 2)

    def send_text(self, text):
        self.calls.append(("text", len(text)))
        self.typed.append(text)
        if text == "\t" and self.tab_into_password:
            self.password = True
        return self.partial or (2, 2)

    def release_keys(self, modifiers, key, char=None):
        self.calls.append(("release_keys", list(modifiers), key, char))

    def send_keys(self, modifiers, key, char):
        self.calls.append(("keys", modifiers, key, char))
        self.keys.append((modifiers, key, char))
        return self.partial or (2, 2)

    def focused_password(self):
        self.calls.append("focused_password")
        return self.password

    def release(self, button):
        self.calls.append(("release", button))


class Page(FakePage):
    """A Chrome page that also answers the focused-field probe and takes keys and text."""

    def __init__(self):
        super().__init__()
        self.focus = "ok"

    async def call(self, method, params=None):
        if method == "Runtime.evaluate" and params.get("expression") == point_cdp_ops.FOCUS:
            self.calls.append((method, params))
            return {"result": {"value": self.focus}}
        if method.startswith("Input."):
            self.dispatched = True
        return await super().call(method, params)

    def sent(self, method):
        return [params for name, params in self.calls if name == method]


class PointFixture(ClickFixture):
    def setUp(self):
        super().setUp()
        self.pointer = Pointer()

    async def point(self, op, **extra):
        message = {"type": "window_point", "request_id": "r1", "grant_id": "g1", "agent": "alice",
                   "line": "line-1", "op": op}
        if op in ("scroll", "drag"):
            message |= {"snapshot": self.snapshot, "x": 100, "y": 100, "screen": [200, 150]}
        if op == "drag":
            message |= {"x2": 200, "y2": 200, "screen2": [300, 250]}
        message |= extra
        await self.shares.dispatch(message)
        await asyncio.gather(*self.shares.tasks)
        return [item for item in self.socket.sent if isinstance(item, dict)
                and item["type"] == "window_element_result"][-1]

    async def clicked(self):
        self.assertEqual("completed", (await self.click())["status"])

    def operations(self):
        return [row["operation"] for row in self.rows_for()]

    def rows_for(self):
        import json
        return [json.loads(call.args[4]) for call in self.audit.append.call_args_list
                if call.args[3].startswith("point_")]


class CursorRouteTests(PointFixture):
    def setUp(self):
        super().setUp()
        self.shares.clicks.pointer = lambda hwnd: self.pointer

    async def test_scroll_turns_the_real_wheel_at_the_converted_point_with_the_same_consent(self):
        reply = await self.point("scroll", dx=1, dy=-3)
        self.assertEqual(("completed", "cursor"), (reply["status"], reply["route"]))
        self.assertEqual([((200, 150), 1, -3)], self.pointer.wheel)
        self.assertEqual((5, 5), self.pointer.cursor_at)  # the cursor is put back
        self.assertIn("mouse and keyboard", self.ask.await_args.args[1])
        await self.click()
        self.assertEqual(1, self.ask.await_count)  # one consent covers every kind of input in the grant
        self.assertEqual("screen_window_scroll", self.rows_for()[0]["operation"])

    async def test_drag_presses_moves_through_a_checked_path_and_releases_in_one_send(self):
        reply = await self.point("drag")
        self.assertEqual("completed", reply["status"])
        spots = self.pointer.drag[0]
        self.assertEqual(((200, 150), (300, 250)), (spots[0], spots[-1]))
        self.assertGreater(len(spots), 2)
        self.assertEqual(spots, [p for p in spots if 108 <= p[0] <= 492 and 80 <= p[1] <= 342])
        row = self.rows_for()[0]
        self.assertEqual(([200, 150], [300, 250]), (row["screen"], row["to_screen"]))

    async def test_a_drag_over_another_window_or_a_partial_send_is_refused_or_released(self):
        self.pointer.covered = {(300, 250)}
        reply = await self.point("drag")
        self.assertEqual("failed", reply["status"])
        self.assertEqual("covered", reply["reason"])
        self.assertEqual([], self.pointer.drag)
        self.pointer.covered = set()
        self.pointer.partial = (1, 5)
        reply = await self.point("drag")
        self.assertEqual("unconfirmed", reply["status"])
        self.assertIn(("release", "left"), self.pointer.calls)

    async def test_every_point_refusal_of_click_holds_for_scroll_and_drag(self):
        self.pointer.under = 99
        for op in ("scroll", "drag"):
            self.assertEqual("covered", (await self.point(op, dy=1))["reason"])
        self.pointer.under = 10
        self.pointer.image = sorted(HARD_FLOOR)[0]
        self.assertIn("never clickable", (await self.point("scroll", dy=1))["error"])
        self.pointer.image = "editor.exe"
        self.pointer.minimized = True
        self.assertIn("minimised", (await self.point("drag"))["error"])
        self.pointer.minimized = False
        self.access.grant["process"] = sorted(HARD_FLOOR)[0]
        self.assertEqual(FLOOR, (await self.point("scroll", dy=1))["error"])
        self.access.grant["process"] = "editor.exe"
        self.snapshot = "unknown"
        for op in ("scroll", "drag"):
            reply = await self.point(op, dy=1)
            self.assertEqual(("failed", "stale"), (reply["status"], reply["reason"]))
        self.assertEqual([], self.pointer.wheel + self.pointer.drag)

    async def test_a_point_outside_the_client_area_or_that_disagrees_is_refused(self):
        reply = await self.point("scroll", dy=1, x=2, y=2, screen=[102, 52])
        self.assertIn("frame or title bar", reply["error"])
        self.assertIn("disagree", (await self.point("scroll", dy=1, screen=[201, 150]))["error"])
        self.backend.regions = [(300, 100, 492, 342)]  # the window moved since the snapshot
        self.assertEqual(STALE, (await self.point("drag"))["error"])
        self.assertEqual([], self.pointer.wheel + self.pointer.drag)

    async def test_the_deadline_and_a_declined_consent_stop_every_operation_before_input(self):
        self.ask.return_value = False
        for op, extra in (("scroll", {"dy": 1}), ("drag", {})):
            reply = await self.point(op, **extra)
            self.assertIn("declined", reply["error"])
        self.assertEqual(1, self.ask.await_count)
        self.clock[0] += COOLDOWN + 1
        self.ask.return_value = True

        async def slow(entry, message):
            self.clock[0] += 100  # the person took longer than the server's deadline
            return None
        self.shares.clicks.consent.check = slow
        for op, extra in (("scroll", {"dy": 1}), ("drag", {}), ("click", {})):
            reply = await self.point(op, budget=30, **extra) if op != "click" else await self.click(budget=30)
            self.assertEqual(LATE, reply["error"], op)
        self.assertEqual([], self.pointer.wheel + self.pointer.drag + self.sends())

    async def test_type_and_key_need_a_click_in_this_grant_and_ask_nothing_before_it(self):
        for op, extra in (("type", {"text": "hi"}), ("key", {"keys": "enter"})):
            self.assertEqual(NEEDS_CLICK, (await self.point(op, **extra))["error"])
        self.assertEqual(0, self.ask.await_count)
        await self.clicked()
        self.assertEqual("completed", (await self.point("type", text="hi"))["status"])
        self.assertEqual(["hi"], self.pointer.typed)
        # a new grant (re-granted window) forgets the click
        self.entry["point_clicked"] = None
        self.assertEqual(NEEDS_CLICK, (await self.point("type", text="hi"))["error"])
        await self.clicked()
        self.access.gate.generation += 1  # re-granted: the click of the earlier grant counts for nothing
        self.assertEqual(NEEDS_CLICK, (await self.point("key", keys="enter"))["error"])

    async def test_a_failed_click_does_not_unlock_the_keyboard(self):
        self.pointer.under = 99
        self.assertEqual("failed", (await self.click())["status"])
        self.assertEqual(NEEDS_CLICK, (await self.point("key", keys="enter"))["error"])

    async def test_text_goes_to_the_keyboard_and_is_never_logged(self):
        await self.clicked()
        reply = await self.point("type", text="secret words\n\tmore")
        self.assertEqual("completed", reply["status"])
        self.assertEqual("secret words\n\tmore", "".join(self.pointer.typed))
        self.assertEqual(["secret words", "\n", "\t", "more"], self.pointer.typed)  # each Tab or Enter alone
        logged = str(self.audit.append.call_args_list)
        self.assertNotIn("secret", logged)
        typed = [r for r in self.rows_for() if r["operation"] == "screen_window_type"][0]
        self.assertEqual(18, typed["characters"])

    async def test_a_password_field_or_one_that_cannot_be_told_is_never_typed_into(self):
        await self.clicked()
        for state, wanted in ((True, "password"), (None, "cannot be inspected")):
            self.pointer.password = state
            for op, extra in (("type", {"text": "x"}), ("key", {"keys": "a"}), ("key", {"keys": "space"})):
                reply = await self.point(op, **extra)
                self.assertEqual("failed", reply["status"])
                self.assertIn(wanted, reply["error"])
        self.assertEqual([], self.pointer.typed + self.pointer.keys)
        self.pointer.password = True  # keys that only move or edit are not typing
        self.assertEqual("completed", (await self.point("key", keys="tab"))["status"])
        self.assertEqual("completed", (await self.point("key", keys="ctrl+a"))["status"])

    async def test_a_tab_that_moves_the_focus_into_a_password_field_stops_the_typing_there(self):
        await self.clicked()
        self.pointer.tab_into_password = True
        reply = await self.point("type", text="safe\tsecret")
        self.assertEqual("failed", reply["status"])
        self.assertIn("password field", reply["error"])
        self.assertIn("5 of 11 characters were typed", reply["error"])  # "safe" and the Tab, not the rest
        self.assertEqual(["safe", "\t"], self.pointer.typed)
        self.assertNotIn("secret", str(self.audit.append.call_args_list) + reply["error"])
        self.pointer.typed.clear()
        self.pointer.password = False  # an Enter or Tab that leaves a safe field changes nothing
        self.pointer.tab_into_password = False
        self.assertEqual("completed", (await self.point("type", text="a\tb\nc"))["status"])
        self.assertEqual(["a", "\t", "b", "\n", "c"], self.pointer.typed)

    async def test_a_focus_that_cannot_be_told_after_a_tab_also_stops_the_typing(self):
        await self.clicked()
        states = iter([False, None])
        self.pointer.focused_password = lambda: next(states)
        reply = await self.point("type", text="a\tb")
        self.assertIn("cannot be inspected", reply["error"])
        self.assertEqual(["a", "\t"], self.pointer.typed)

    async def test_every_run_of_typed_text_is_guarded_again_after_the_blocking_inspection(self):
        await self.clicked()
        scenarios = (("late", lambda: self.clock.__setitem__(0, self.clock[0] + 100), LATE),
                     ("foreground", lambda: setattr(self.pointer, "front", 77), point_cursor.CHANGED),
                     ("revoked", lambda: self.access.gate.revoked.set(), "revoked"))  # last: ends the grant
        for name, change, wanted in scenarios:
            with self.subTest(name):
                self.pointer.typed.clear()

                def inspect(change=change, inspections=[]):  # noqa: B006 - a fresh list per case
                    inspections.append(1)
                    if len(inspections) == 2:  # while the second run's field is being looked at
                        change()
                    return False
                self.pointer.focused_password = inspect
                reply = await self.point("type", text="a\tb")
                self.assertEqual("failed", reply["status"])
                self.assertIn(wanted, reply["error"])
                self.assertIn("2 of 3 characters were typed", reply["error"])
                self.assertEqual(["a", "\t"], self.pointer.typed)  # the "b" never went out
                self.pointer.front = 10

    async def test_a_cut_short_send_lifts_every_key_it_may_hold_down(self):
        await self.clicked()
        self.pointer.partial = (3, 8)
        reply = await self.point("key", keys="ctrl+shift+a")
        self.assertEqual("unconfirmed", reply["status"])
        self.assertIn(("release_keys", [0x11, 0x10], 65, None), self.pointer.calls)
        reply = await self.point("type", text="x\ty")
        self.assertEqual("unconfirmed", reply["status"])
        self.assertIn(("release_keys", [9], 13, None), self.pointer.calls)
        self.assertEqual(["x"], self.pointer.typed[-1:])  # nothing more goes after a short send

    async def test_keys_are_sent_as_virtual_keys_and_combos_that_leave_the_window_are_refused(self):
        await self.clicked()
        await self.point("key", keys="ctrl+shift+a")
        await self.point("key", keys="enter")
        await self.point("key", keys="?")
        self.assertEqual([([0x11, 0x10], 65, None), ([], 13, None), ([], None, "?")], self.pointer.keys)
        before = self.ask.await_count
        for keys in ("meta+d", "meta", "alt+tab", "alt+esc", "ctrl+esc", "ctrl+shift+esc", "alt+f4", "ctrl+c",
                     "ctrl+x", "ctrl+v", "ctrl+insert", "shift+insert", "shift+delete", "ctrl+alt+delete",
                     "meta+l", "ctrl+ctrl"):
            reply = await self.point("key", keys=keys)
            self.assertEqual("failed", reply["status"], keys)
        self.assertEqual(3, len(self.pointer.keys))
        self.assertEqual(before, self.ask.await_count)  # refused before the person is asked anything

    async def test_a_foreground_that_changes_while_checking_the_field_stops_the_typing(self):
        await self.clicked()
        self.pointer.foreground_after_focus = None
        original = self.pointer.focused_password

        def stolen():
            self.pointer.front = 77  # something else took the foreground during the check
            return original()
        self.pointer.focused_password = stolen
        reply = await self.point("type", text="x")
        self.assertEqual("failed", reply["status"])
        self.assertEqual([], self.pointer.typed)

    async def test_revocation_and_a_closed_window_stop_the_new_operations_like_a_click(self):
        self.access.gate.revoked.set()
        for op, extra in (("scroll", {"dy": 1}), ("drag", {}), ("type", {"text": "x"}),
                          ("key", {"keys": "a"})):
            self.assertEqual("failed", (await self.point(op, **extra))["status"])
        self.assertEqual([], self.pointer.wheel + self.pointer.drag + self.pointer.typed + self.pointer.keys)


class CdpRouteTests(PointFixture):
    def setUp(self):
        super().setUp()
        self.page = Page()
        self.access.grant["process"] = "chrome.exe"
        self.shares.chrome.page = AsyncMock(return_value=self.page)
        self.shares.clicks.pointer = Mock(side_effect=AssertionError("the cursor route must not run"))
        self.snapshot = self.take()

    async def test_scroll_is_a_wheel_event_at_the_page_point_and_never_the_cursor(self):
        reply = await self.point("scroll", dx=2, dy=-3)
        self.assertEqual(("completed", "cdp", "quiet"), (reply["status"], reply["route"], reply["settle"]))
        event = self.page.sent("Input.dispatchMouseEvent")[0]
        self.assertEqual(("mouseWheel", 92.0, 70.0, 200, 300),
                         (event["type"], event["x"], event["y"], event["deltaX"], event["deltaY"]))
        self.ask.assert_not_called()
        self.assertEqual("cdp", self.rows_for()[0]["route"])

    async def test_a_zoomed_page_scales_the_wheel_point(self):
        self.page.viewport = [192, 131, 1]
        await self.point("scroll", dy=1)
        event = self.page.sent("Input.dispatchMouseEvent")[0]
        self.assertEqual((46.0, 35.0, -100), (event["x"], event["y"], event["deltaY"]))

    async def test_drag_presses_moves_and_releases_through_the_path_in_page_pixels(self):
        reply = await self.point("drag")
        self.assertEqual("completed", reply["status"])
        events = self.page.sent("Input.dispatchMouseEvent")
        kinds = [event["type"] for event in events]
        self.assertEqual(("mouseMoved", "mousePressed"), tuple(kinds[:2]))
        self.assertEqual("mouseReleased", kinds[-1])
        self.assertEqual({"mouseMoved"}, set(kinds[2:-1]))
        self.assertEqual(((92.0, 70.0), (192.0, 170.0)), ((events[1]["x"], events[1]["y"]),
                                                          (events[-1]["x"], events[-1]["y"])))
        self.assertEqual([1] * (len(events) - 2), [e["buttons"] for e in events[1:-1]])

    async def test_a_drag_whose_move_fails_never_leaves_the_button_down(self):
        real = self.page.call

        async def failing(method, params=None):
            if (method == "Input.dispatchMouseEvent" and params["type"] == "mouseMoved"
                    and params["buttons"] == 1):
                self.page.calls.append((method, params))
                self.page.dispatched = True
                raise CDPError("target closed")
            return await real(method, params)
        self.page.call = failing
        reply = await self.point("drag")
        self.assertEqual("unconfirmed", reply["status"])
        self.assertIn("the button was released", reply["error"])
        self.assertEqual("mouseReleased", self.page.sent("Input.dispatchMouseEvent")[-1]["type"])

    async def test_type_needs_a_click_then_inserts_text_in_a_field_that_is_not_a_password(self):
        self.assertEqual(NEEDS_CLICK, (await self.point("type", text="hi"))["error"])
        self.assertEqual([], self.page.sent("Input.insertText"))
        await self.clicked()
        reply = await self.point("type", text="hello\nworld")
        self.assertEqual(("completed", "cdp"), (reply["status"], reply["route"]))
        self.assertEqual([{"text": "hello\nworld"}], self.page.sent("Input.insertText"))
        self.assertEqual(11, self.rows_for()[-1]["characters"])
        self.assertNotIn("hello", str(self.audit.append.call_args_list))

    async def test_a_password_field_and_a_field_that_cannot_be_inspected_refuse_typing(self):
        await self.clicked()
        for focus, wanted in (("password", "password field"), ("unknown", "cannot be inspected"),
                              ("none", "cannot be inspected")):
            self.page.focus = focus
            for op, extra in (("type", {"text": "x"}), ("key", {"keys": "a"})):
                reply = await self.point(op, **extra)
                self.assertEqual("failed", reply["status"])
                self.assertIn(wanted, reply["error"])
        self.assertEqual([], self.page.sent("Input.insertText") + self.page.sent("Input.dispatchKeyEvent"))
        self.page.focus = "password"  # moving and editing keys are not typing
        self.assertEqual("completed", (await self.point("key", keys="tab"))["status"])

    def test_the_focus_probe_looks_through_shadow_roots_frames_and_css_masks(self):
        for part in ("shadowRoot", "contentDocument", "webkitTextSecurity", "'unknown'", "password"):
            self.assertIn(part, point_cdp_ops.FOCUS)

    async def test_keys_are_key_events_with_modifiers_and_text_only_when_they_type(self):
        await self.clicked()
        await self.point("key", keys="enter")
        await self.point("key", keys="ctrl+a")
        await self.point("key", keys="shift+x")
        await self.point("key", keys="f5")
        events = self.page.sent("Input.dispatchKeyEvent")
        downs = [e for e in events if e["type"] != "keyUp"]
        self.assertEqual([("keyDown", "Enter", "\r", 0), ("rawKeyDown", "a", None, 2),
                          ("keyDown", "X", "X", 8), ("rawKeyDown", "F5", None, 0)],
                         [(e["type"], e["key"], e.get("text"), e["modifiers"]) for e in downs])
        self.assertEqual(4, len([e for e in events if e["type"] == "keyUp"]))

    async def test_shift_with_a_symbol_key_is_refused_because_its_character_depends_on_the_layout(self):
        await self.clicked()
        for keys in ("shift+1", "shift+/", "shift+;"):
            reply = await self.point("key", keys=keys)
            self.assertEqual("failed", reply["status"], keys)
            self.assertIn("screen_window_type", reply["error"])
        self.assertEqual([], self.page.sent("Input.dispatchKeyEvent"))
        self.assertEqual("completed", (await self.point("key", keys="shift+space"))["status"])
        self.assertEqual("completed", (await self.point("key", keys="shift+tab"))["status"])

    async def test_blocked_combos_never_reach_the_page_and_other_keys_still_work(self):
        await self.clicked()
        for keys in ("ctrl+alt+delete", "meta+l", "ctrl+c", "ctrl+v", "ctrl+x", "alt+f4", "shift+delete",
                     "bogus+key", "ctrl", ""):
            self.assertEqual("failed", (await self.point("key", keys=keys))["status"], keys)
        self.assertEqual([], self.page.sent("Input.dispatchKeyEvent"))
        # the Windows key does nothing to a page, so a page route may send it
        self.assertEqual("completed", (await self.point("key", keys="meta+d"))["status"])

    async def test_the_click_rules_hold_for_scroll_and_drag_in_a_page(self):
        self.shares.clicks.sources = areas((300, 80, 492, 211))
        self.page.viewport = [192, 131, 1]
        for op in ("scroll", "drag"):
            self.assertIn("browser's own controls", (await self.point(op, dy=1))["error"])
        self.shares.clicks.sources = areas((108, 80, 492, 342))
        self.page.viewport = [384, 262, 1.5]
        self.assertIn("pinch-zoomed", (await self.point("scroll", dy=1))["error"])
        self.page.viewport = [384, 262, 1]
        self.access.gate.revoked.set()
        self.assertEqual(GONE, (await self.point("drag"))["error"])
        self.assertEqual([], self.page.sent("Input.dispatchMouseEvent"))

    async def test_the_deadline_stops_a_page_operation_that_starts_late(self):
        await self.clicked()

        async def slow_page(access):
            self.clock[0] += 100  # the helper was busy past the server's deadline
            return self.page
        self.shares.chrome.page = slow_page
        for op in ("scroll", "drag", "type", "key"):
            extra = {"text": "x"} if op == "type" else {"keys": "a"} if op == "key" else {"dy": 1}
            reply = await self.point(op, budget=30, **extra)
            self.assertEqual(LATE, reply["error"], op)
        self.assertEqual(
            [], self.page.sent("Input.insertText") + self.page.sent("Input.dispatchKeyEvent")
            + [e for e in self.page.sent("Input.dispatchMouseEvent") if e["type"] == "mouseWheel"])


class PureRuleTests(unittest.TestCase):
    def test_arguments_validate_each_operation_and_the_audit_name_is_stable(self):
        self.assertEqual("click", which({}))
        self.assertEqual("invalid", which({"op": "shell"}))
        self.assertEqual(("scroll", {"dx": 0, "dy": 2}), arguments({"op": "scroll", "dy": 2}))
        for bad in ({"op": "scroll"}, {"op": "scroll", "dy": 51}, {"op": "scroll", "dy": True},
                    {"op": "scroll", "dy": 1.5}, {"op": "type", "text": ""}, {"op": "type", "text": "\x07"},
                    {"op": "type", "text": "a" * 501}, {"op": "key", "keys": "ctrl+c"},
                    {"op": "key", "keys": "alt"},
                    {"op": "warp"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                arguments(bad)
        self.assertEqual(("key", {"names": ("ctrl", "a")}), arguments({"op": "key", "keys": "Ctrl+A"}))

    def test_the_drag_path_is_two_ends_and_a_few_steps_between_at_whole_pixels(self):
        spots = path([(0, 0), (400, 100)])
        self.assertEqual(((0, 0), (400, 100)), (spots[0], spots[-1]))
        self.assertEqual(11, len(spots))
        self.assertTrue(all(isinstance(v, int) for spot in spots for v in spot))
        self.assertEqual(3, len(path([(0, 0), (10, 10)])))

    def test_text_rules_and_the_text_inserting_test(self):
        self.assertEqual("a\tb\nc", point_keys.clean_text("a\tb\nc"))
        for bad in (None, 5, "", "x" * 501, "a\x1bb", "a\x7f"):
            with self.assertRaises(ValueError):
                point_keys.clean_text(bad)
        for keys, typing in (("a", True), ("shift+a", True), ("space", True), ("enter", False),
                             ("ctrl+a", False), ("tab", False), ("f5", False), ("alt+x", False)):
            self.assertEqual(typing, point_keys.inserts_text(keys.split("+")), keys)
        self.assertEqual(("a", "KeyA", 65), point_keys.cdp_event("a"))
        self.assertEqual(("5", "Digit5", 53), point_keys.cdp_event("5"))
        self.assertEqual(("?", "", 0), point_keys.cdp_event("?"))
        self.assertEqual(([0x11, 0x12], 65), point_keys.virtual_keys(["ctrl", "alt", "a"]))
        self.assertEqual(([], None), point_keys.virtual_keys(["?"]))

    def test_the_real_pointer_adds_the_shift_a_layout_needs_and_lifts_what_it_pressed(self):
        sent = []

        class User:
            def VkKeyScanW(self, code):  # a US layout: "?" is Shift+/, "x" is plain, "~" is missing here
                return {ord("?"): 0x01BF, ord("x"): 0x0058, ord("@"): 0x0732, ord("~"): -1}[code]

            def SendInput(self, count, items, size):
                sent.append([(i.union.ki.wVk, i.union.ki.dwFlags) for i in items])
                return count
        pointer = point_win32.Win32Pointer.__new__(point_win32.Win32Pointer)
        pointer.user = User()
        down, up = 0, point_win32.KEY_UP
        self.assertEqual((4, 4), pointer.send_keys([], None, "?"))
        self.assertEqual([(0x10, down), (0xBF, down), (0xBF, up), (0x10, up)], sent[-1])  # Shift held for it
        pointer.send_keys([0x10], None, "x")  # an explicit Shift is not pressed twice
        self.assertEqual([(0x10, down), (0x58, down), (0x58, up), (0x10, up)], sent[-1])
        pointer.send_keys([], None, "@")  # a layout that needs Shift, Ctrl and Alt for it
        self.assertEqual([0x10, 0x11, 0x12], [vk for vk, flags in sent[-1][:3]])
        pointer.release_keys([0x11], 65)
        self.assertEqual([(65, up), (0x11, up)], sent[-1])
        before = len(sent)
        with self.assertRaisesRegex(Exception, "not on the keyboard layout"):
            pointer.send_keys([], None, "~")
        self.assertEqual(before, len(sent))
        pointer.send_text("a\tb")  # characters as Unicode events, the Tab as the key
        self.assertEqual([(0, 4), (0, 4 | up), (9, down), (9, up), (0, 4), (0, 4 | up)], sent[-1])

    def test_the_real_input_structures_carry_a_keyboard_member(self):
        item = point_win32.Input()
        item.type, item.union.ki.wVk = 1, 13
        self.assertEqual((1, 13), (item.type, item.union.ki.wVk))
        self.assertIn(0x2E, point_win32.EXTENDED_KEYS)


if __name__ == "__main__":
    unittest.main()
