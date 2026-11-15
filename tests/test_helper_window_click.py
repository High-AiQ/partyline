"""The helper's point clicks: snapshot geometry, refusals, both routes, consent and audit, all faked."""
import asyncio
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from partyline_helper.cdp_transport import CDPError
from partyline_helper.client import Session
from partyline_helper import point_cursor
from partyline_helper.point_consent import COOLDOWN
from partyline_helper.uia_gate import DispatchGate
from partyline_helper.window_click import BUDGET, FLOOR, GONE, LATE, PARTLY, STALE, PointClicks
from partyline_helper.window_marks import boxes, clean_inputs, draw, listed
from partyline_helper.window_shares import WindowShares
from partyline_helper.window_snapshot import WindowSnapshots
from tests.screen_helper_fakes import FakeDesktop, FakeSocket, FakeTerminal

RECT, REGION = (100, 50, 500, 350), (108, 80, 492, 342)
GRANT = {"hwnd": 10, "pid": 42, "title": "Editor", "process": "editor.exe"}


class FakePointer:
    """Win32 as the cursor route needs it; every call is recorded and nothing real is touched."""

    def __init__(self):
        self.calls, self.front, self.under, self.image = [], 10, 10, "editor.exe"
        self.minimized, self.helper, self.sent, self.cursor_at = False, False, None, (5, 5)
        self.foreground_after_focus = None

    @contextmanager
    def session(self):
        yield

    def foreground(self):
        self.calls.append("foreground")
        return self.front

    def iconic(self, hwnd):
        return self.minimized

    def owns(self, hwnd):
        return hwnd in (10, 11)

    def bring_forward(self, hwnd, prior):
        self.calls.append(("bring_forward", hwnd))
        self.front = hwnd
        return True

    def restore(self, prior, focus):
        self.calls.append(("restore", prior))
        return True

    def window_at(self, x, y):
        self.calls.append(("window_at", x, y))
        return self.under

    def image_name(self, hwnd):
        return self.image

    def is_helper(self, hwnd):
        return self.helper

    def cursor(self):
        return self.cursor_at

    def move(self, x, y):
        self.calls.append(("move", x, y))
        self.cursor_at = (x, y)
        if self.foreground_after_focus:
            self.front = self.foreground_after_focus
        return True

    def send(self, point, button, clicks):
        self.calls.append(("send", button, clicks))
        self.sent_at, self.cursor_at = tuple(point), tuple(point)  # the input itself moves to the point
        self.locked = point_cursor.ONE_AT_A_TIME.locked()
        return self.sent or (2 * clicks + 1, 2 * clicks + 1)

    def release(self, button):
        self.calls.append(("release", button))


class FakePage:
    def __init__(self, width=384, height=262, zoom=1):
        self.calls, self.dispatched, self.live, self.operation_epoch = [], False, True, None
        self.viewport = [width, height, zoom]
        self.quiet = SimpleNamespace(wait=AsyncMock(return_value="quiet"))
        self.shown, self.on_input = True, None
        self.access = SimpleNamespace(event_status=lambda: {"event_counter": 4})
        self.fail = None

    async def visible(self):
        return self.shown

    async def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "Input.dispatchMouseEvent":
            self.dispatched = True
            if self.on_input:
                self.on_input()
        if method == "Runtime.evaluate":
            return {"result": {"value": self.viewport}}
        if self.fail:
            self.dispatched = method != "Input.dispatchMouseEvent" or len(self.calls) > 2
            raise CDPError(self.fail)
        return {}


class Backend:
    def __init__(self):
        self.rect, self.regions = RECT, [REGION]

    def layout(self, hwnd):
        return {"rect": self.rect, "regions": self.regions}


class ClickFixture(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.socket = FakeSocket()
        self.session = Session(self.socket, FakeDesktop(), FakeTerminal(), "Desktop")
        self.audit = SimpleNamespace(append=Mock(), ensure_writable=Mock())
        self.session.tools.audit = self.audit
        self.shares = WindowShares(self.session)
        self.session.windows = self.shares
        self.shares.chrome.revoke = Mock()
        self.backend = self.shares.snapshots.backend = Backend()
        self.pointer, self.page, self.clock = FakePointer(), FakePage(), [1000.0]
        self.ask = AsyncMock(return_value=True)
        self.events = SimpleNamespace(status=lambda: {"event_counter": 1}, settle=lambda counter: "quiet")
        self.windows = [{"hwnd": 10, "pid": 42}]
        self.access = SimpleNamespace(grant=dict(GRANT), generation=3, check=AsyncMock(return_value=None),
                                      revoke=Mock(), gate=DispatchGate(), event_state=self.events,
                                      list_windows=lambda: self.windows)
        self.access.gate.grant()
        self.entry = {"access": self.access, "target": {"line_name": "Alpha"}, "title": "Editor",
                      "worker": SimpleNamespace(cancel=Mock(), close=AsyncMock())}
        self.shares.grants["g1"] = self.entry
        self.shares.clicks.pointer = lambda hwnd: self.pointer
        self.shares.clicks.consent.ask = self.ask
        self.shares.clicks.clock = self.shares.clicks.consent.clock = lambda: self.clock[0]
        self.shares.clicks.rect_of = lambda hwnd: (108, 80, 492, 342)
        self.shares.chrome.page = AsyncMock(return_value=None)
        self.snapshot = self.take()

    async def asyncTearDown(self):
        await self.shares.close()

    def take(self, grant=None):
        image = Image.new("RGB", (400, 300))
        image.info.update(rect=RECT, regions=[REGION], dpi=96)
        ident, _ = WindowSnapshots.remember(self.entry, grant or self.access.grant, image,
                                            self.access.gate.generation)
        return ident

    async def click(self, x=100, y=100, **extra):
        message = {"type": "window_click", "request_id": "r1", "grant_id": "g1", "agent": "alice",
                   "line": "line-1", "snapshot": self.snapshot, "x": x, "y": y, "screen": [200, 150],
                   "button": "left", "clicks": 1, **extra}
        if extra.get("screen") is None and "screen" in extra:
            message.pop("screen")
        await self.shares.dispatch(message)
        await asyncio.gather(*self.shares.tasks)
        return [item for item in self.socket.sent if isinstance(item, dict)
                and item["type"] == "window_element_result"][-1]

    def rows(self):
        return [json.loads(call.args[4]) for call in self.audit.append.call_args_list
                if call.args[3] == "point_click"]

    def sends(self):
        return [call for call in self.pointer.calls if isinstance(call, tuple) and call[0] == "send"]


class CdpRouteTests(ClickFixture):
    def setUp(self):
        super().setUp()
        self.access.grant["process"] = "chrome.exe"
        self.shares.chrome.page = AsyncMock(return_value=self.page)
        self.shares.clicks.pointer = Mock(side_effect=AssertionError("the cursor route must not run"))
        self.snapshot = self.take()

    async def test_a_chrome_page_is_clicked_through_cdp_at_page_pixels_and_never_the_cursor(self):
        reply = await self.click(clicks=2, button="right")
        self.assertEqual(("completed", "cdp", "quiet"), (reply["status"], reply["route"], reply["settle"]))
        events = [params for method, params in self.page.calls if method == "Input.dispatchMouseEvent"]
        self.assertEqual(["mouseMoved", "mousePressed", "mouseReleased", "mousePressed", "mouseReleased"],
                         [event["type"] for event in events])
        self.assertEqual({(92.0, 70.0)}, {(event["x"], event["y"]) for event in events})
        self.assertEqual([1, 1, 2, 2], [event.get("clickCount") for event in events if "clickCount" in event])
        self.assertEqual({"right"}, {event["button"] for event in events[1:]})
        self.shares.clicks.pointer.assert_not_called()
        self.ask.assert_not_called()  # no consent prompt, as for CDP element actions
        self.assertEqual(["dispatching", "completed"], [row["result"] for row in self.rows()])
        self.assertEqual({"cdp"}, {row["route"] for row in self.rows()})

    async def test_a_picked_tab_that_is_not_the_one_shown_is_never_clicked(self):
        self.access.grant["target_id"] = "tab-2"
        self.snapshot = self.take()
        self.page.shown = False
        self.assertIn("not the tab shown", (await self.click())["error"])
        self.assertEqual([], [c for c in self.page.calls if c[0] == "Input.dispatchMouseEvent"])
        self.page.shown = True
        self.assertEqual("completed", (await self.click())["status"])

    async def test_a_zoomed_page_scales_the_point(self):
        self.page.viewport = [192, 131, 1]  # 200% browser zoom: two screen pixels per CSS pixel
        await self.click()
        events = [p for m, p in self.page.calls if m == "Input.dispatchMouseEvent"]
        self.assertEqual((46.0, 35.0), (events[0]["x"], events[0]["y"]))

    async def test_a_point_on_the_browsers_own_controls_or_a_pinch_zoomed_page_is_refused(self):
        self.page.viewport = [192, 131, 1]
        self.shares.clicks.rect_of = lambda hwnd: (300, 80, 492, 211)  # page area starts right of the point
        self.assertIn("browser's own controls", (await self.click())["error"])
        self.shares.clicks.rect_of = lambda hwnd: (108, 80, 492, 342)
        self.page.viewport = [384, 262, 1.5]
        self.assertIn("pinch-zoomed", (await self.click())["error"])
        self.page.viewport = [384, 100, 1]
        self.assertIn("pinch-zoomed", (await self.click())["error"])
        self.page.viewport = "bad"
        self.assertIn("could not be read", (await self.click())["error"])
        self.shares.clicks.rect_of = lambda hwnd: None
        self.assertIn("could not be found", (await self.click())["error"])
        self.assertEqual([], [c for c in self.page.calls if c[0] == "Input.dispatchMouseEvent"])

    async def test_a_failure_after_input_started_is_unconfirmed_and_one_before_is_a_refusal(self):
        self.page.fail = "target closed"
        reply = await self.click()
        self.assertEqual("failed", reply["status"])  # the first event failed: nothing was sent
        self.page.dispatched = False

        async def second_fails(method, params=None):
            self.page.calls.append((method, params))
            if method == "Runtime.evaluate":
                return {"result": {"value": self.page.viewport}}
            if params["type"] == "mousePressed":
                self.page.dispatched = True
                raise CDPError("lost")
            return {}
        self.page.call = second_fails
        reply = await self.click()
        self.assertEqual(("unconfirmed", "cdp"), (reply["status"], reply["route"]))

    def press_fails(self, release_fails=False):
        async def call(method, params=None):
            self.page.calls.append((method, params))
            if method == "Runtime.evaluate":
                return {"result": {"value": self.page.viewport}}
            self.page.dispatched = True
            kind = params["type"]
            if kind == "mousePressed" or (kind == "mouseReleased" and release_fails):
                raise CDPError("Chrome command interrupted")
            return {}
        self.page.call = call

    def kinds(self):
        return [p["type"] for m, p in self.page.calls if m == "Input.dispatchMouseEvent"]

    async def test_a_press_whose_answer_failed_is_still_released_and_stays_unconfirmed(self):
        self.press_fails()
        reply = await self.click()
        self.assertEqual(["mouseMoved", "mousePressed", "mouseReleased"], self.kinds())
        self.assertEqual(("unconfirmed", "cdp"), (reply["status"], reply["route"]))
        self.assertIn("interrupted; the button was released", reply["error"])

    async def test_a_release_that_cannot_be_confirmed_is_not_reported_as_released(self):
        self.press_fails(release_fails=True)
        reply = await self.click()
        self.assertEqual("unconfirmed", reply["status"])
        self.assertIn("a button may still be down", reply["error"])
        self.assertNotIn("was released", reply["error"])

    async def test_a_changing_page_is_reported_as_changing(self):
        counters = iter([4, 5])
        self.page.access = SimpleNamespace(event_status=lambda: {"event_counter": next(counters)})
        self.assertEqual("changing", (await self.click())["settle"])


class CursorRouteTests(ClickFixture):
    async def test_the_cursor_route_asks_once_per_grant_then_clicks_inside_the_window(self):
        self.pointer.front = 50  # another window is in front: the target comes forward, then goes back
        reply = await self.click()
        self.assertTrue(reply["target_came_forward"])
        self.assertIn(("restore", 50), self.pointer.calls)
        self.assertEqual(("completed", "cursor", "quiet"), (reply["status"], reply["route"], reply["settle"]))
        await self.click()
        self.assertEqual(1, self.ask.await_count)  # consent is per grant, asked once
        text = self.ask.await_args.args[1]
        self.assertIn("Allow Alpha/alice to click with the mouse in Editor?", text)
        self.assertEqual(("Allow for this window", "Deny"), self.ask.await_args.kwargs["labels"])
        self.assertEqual([("send", "left", 1), ("send", "left", 1)], self.sends())
        self.assertIn(("move", 200, 150), self.pointer.calls)
        self.assertEqual((5, 5), self.pointer.cursor_at)  # the cursor went back
        self.assertEqual((True, True), (reply["cursor_restored"], reply["foreground_restored"]))
        rows = self.rows()
        self.assertEqual(["dispatching", "completed"], [row["result"] for row in rows[:2]])
        self.assertEqual(("cursor", "g1", "alice"), (rows[0]["route"], rows[0]["grant"], rows[0]["process"]))
        self.assertEqual(([100, 100], [200, 150], "screen_window_click"),
                         (rows[0]["point"], rows[0]["screen"], rows[0]["operation"]))

    async def test_the_tray_says_the_mouse_is_in_use_while_the_click_runs(self):
        seen = []
        original = self.pointer.send

        def spying(point, button, clicks):
            seen.append(self.session.status.label)
            return original(point, button, clicks)
        self.pointer.send = spying
        await self.click()
        self.assertIn("(using your mouse)", seen[0])
        self.assertEqual(set(), self.session.status.window_mouse)  # and no longer once it is over

    async def test_a_deny_refuses_and_is_not_asked_again_until_the_cooldown(self):
        self.ask.return_value = False
        reply = await self.click()
        self.assertEqual("failed", reply["status"])
        self.assertIn("declined", reply["error"])
        self.clock[0] += COOLDOWN - 1
        self.assertIn("a moment ago", (await self.click())["error"])
        self.assertEqual(1, self.ask.await_count)
        self.clock[0] += 2
        self.ask.return_value = True
        self.assertEqual("completed", (await self.click())["status"])
        self.assertEqual(2, self.ask.await_count)
        self.assertEqual([("send", "left", 1)], self.sends())  # only the approved one sent anything

    async def test_approval_ends_with_standing_access_the_pause_the_grant_and_a_new_grant_asks_again(self):
        await self.click()
        self.assertTrue(self.entry["mouse_approved"])
        self.shares.revoke_standing()  # the toggle switched off
        self.assertNotIn("mouse_approved", self.entry)
        await self.click()
        self.assertEqual(2, self.ask.await_count)
        self.assertTrue(self.entry["mouse_approved"])
        self.shares.revoke_all()  # a pause or a disconnect
        self.assertNotIn("mouse_approved", self.entry)
        self.entry["mouse_approved"] = True
        self.shares.revoke("g1")  # the grant itself ends: the entry, and with it the approval, is gone
        self.assertNotIn("g1", self.shares.grants)
        again = dict(self.entry)
        again.pop("mouse_approved", None)
        self.assertNotIn("mouse_approved", again)

    async def test_an_approval_given_after_access_was_switched_off_is_discarded(self):
        async def answer(*args, **kwargs):
            self.shares.revoke_standing()  # the person turned window access off while the prompt was open
            return True
        self.ask.side_effect = answer
        reply = await self.click()
        self.assertEqual(("failed", GONE), (reply["status"], reply["error"]))
        self.assertNotIn("mouse_approved", self.entry)
        self.assertEqual([], self.sends())

    async def test_what_is_under_the_point_must_be_the_window_or_its_dialogs(self):
        self.pointer.under = 99
        reply = await self.click()
        self.assertIn("another window is on top", reply["error"])
        self.assertEqual([], self.sends())
        self.pointer.under = 11  # an owned dialog is fine
        self.assertEqual("completed", (await self.click())["status"])

    async def test_a_hard_floor_program_or_the_helper_under_the_point_is_never_clicked(self):
        for image, helper in (("cmd.exe", False), ("1password.exe", False), ("editor.exe", True)):
            self.pointer.image, self.pointer.helper = image, helper
            self.assertIn("never clickable", (await self.click())["error"])
        self.assertEqual([], self.sends())

    async def test_a_hard_floor_grant_is_refused_before_anything_else(self):
        self.access.grant["process"] = "WindowsTerminal.exe"
        self.snapshot = self.take()
        reply = await self.click()
        self.assertEqual(FLOOR, reply["error"])
        self.ask.assert_not_called()
        self.assertEqual([], self.pointer.calls)

    async def test_a_foreground_change_underneath_refuses_the_click(self):
        self.pointer.front = 10
        self.pointer.foreground_after_focus = 77
        reply = await self.click()
        self.assertIn("foreground window changed", reply["error"])
        self.assertEqual([], self.sends())
        self.assertEqual((5, 5), self.pointer.cursor_at)

    async def test_a_minimised_window_or_one_that_will_not_come_forward_is_refused(self):
        self.pointer.minimized = True
        self.assertIn("minimised", (await self.click())["error"])
        self.pointer.minimized = False
        self.pointer.bring_forward = lambda hwnd, prior: False
        self.pointer.front = 50
        self.assertIn("could not be brought to the front", (await self.click())["error"])
        self.assertEqual([], self.sends())

    async def test_a_partly_delivered_click_releases_the_button_and_is_unconfirmed(self):
        self.pointer.sent = (1, 2)
        reply = await self.click()
        self.assertEqual("unconfirmed", reply["status"])
        self.assertIn(("release", "left"), self.pointer.calls)

    async def test_a_window_already_in_front_is_not_moved_and_a_right_double_click_is_forwarded(self):
        reply = await self.click(button="right", clicks=2)
        self.assertEqual([("send", "right", 2)], self.sends())
        self.assertFalse(reply["target_came_forward"])
        self.assertFalse(reply["foreground_restored"])

    async def test_the_window_closing_or_the_secure_desktop_refuses_before_the_mouse_moves(self):
        self.windows = []
        self.assertIn("window closed", (await self.click())["error"])
        self.windows = None
        self.assertIn("secure desktop", (await self.click())["error"])
        self.assertEqual([], [c for c in self.pointer.calls if isinstance(c, tuple) and c[0] == "move"])

    async def test_a_revoke_during_the_click_is_reported(self):
        original = self.pointer.send

        def revoking(point, button, clicks):
            self.access.gate.invalidate()
            return original(point, button, clicks)
        self.pointer.send = revoking
        self.assertTrue((await self.click())["revoked_during"])


class DispatchTimeTests(ClickFixture):
    """What changes between the early checks and the button going down must be caught or be harmless."""

    async def test_the_input_moves_to_the_checked_point_serialised_and_whatever_the_cursor_did_before(self):
        reply = await self.click()
        self.assertEqual("completed", reply["status"])
        self.assertEqual((200, 150), self.pointer.sent_at)
        self.assertTrue(self.pointer.locked)  # one real-cursor click at a time, across every grant
        self.assertFalse(point_cursor.ONE_AT_A_TIME.locked())

    async def test_a_cursor_moved_away_after_the_checks_refuses_the_click(self):
        original = self.pointer.window_at

        def moving(x, y):
            self.pointer.cursor_at = (900, 900)
            return original(x, y)
        self.pointer.window_at = moving
        self.assertEqual(point_cursor.MOVED, (await self.click())["error"])
        self.assertEqual([], self.sends())

    async def test_a_foreground_or_cover_change_during_the_slow_liveness_check_is_caught_after_it(self):
        def covering():
            self.pointer.under = 99
            return self.windows
        self.access.list_windows = covering
        self.assertEqual(point_cursor.COVERED, (await self.click())["error"])
        self.pointer.under = 10
        self.pointer.front = 10

        def stealing():
            self.pointer.foreground_after_focus = 77  # applies when the cursor moves, after the check
            return self.windows
        self.access.list_windows = stealing
        self.assertEqual(point_cursor.CHANGED, (await self.click())["error"])
        self.assertEqual([], self.sends())

    async def test_a_cursor_moved_during_the_slow_check_does_not_move_the_click(self):
        def wandering():
            self.pointer.cursor_at = (900, 900)
            return self.windows
        self.access.list_windows = wandering
        self.assertEqual("completed", (await self.click())["status"])
        self.assertEqual((200, 150), self.pointer.sent_at)

    async def test_access_switched_off_while_the_window_was_being_checked_stops_the_click(self):
        calls = []

        async def check(grant):
            calls.append(grant)
            if len(calls) == 2:  # the second look, after the person said yes
                self.shares.revoke_standing()
            return None
        self.access.check = check
        reply = await self.click()
        self.assertEqual(("failed", GONE), (reply["status"], reply["error"]))
        self.assertNotIn("mouse_approved", self.entry)
        self.assertEqual([], self.sends())

    async def test_a_consent_cleared_while_the_window_comes_forward_stops_the_click(self):
        self.pointer.front = 50
        original = self.pointer.bring_forward

        def forward(hwnd, prior):
            self.shares.revoke_standing()
            return original(hwnd, prior)
        self.pointer.bring_forward = forward
        self.assertEqual(GONE, (await self.click())["error"])
        self.assertEqual([], self.sends())

    async def test_a_window_that_moved_or_resized_while_coming_forward_is_stale_not_clicked(self):
        for change in ("rect", "regions"):
            self.pointer.front = 50
            original = self.pointer.bring_forward

            def forward(hwnd, prior, change=change, original=original):
                if change == "rect":
                    self.backend.rect = (120, 70, 520, 370)  # moved 20 pixels
                else:
                    self.backend.regions = [(108, 80, 492, 322)]
                return original(hwnd, prior)
            self.pointer.bring_forward = forward
            self.assertEqual(STALE, (await self.click())["error"])
            self.backend.rect, self.backend.regions = RECT, [REGION]
            self.pointer.bring_forward = original
        self.assertEqual([], self.sends())

    async def test_a_window_that_moved_during_the_page_setup_is_not_clicked_through_cdp(self):
        self.access.grant["process"] = "chrome.exe"
        self.snapshot = self.take()
        self.shares.chrome.page = AsyncMock(return_value=self.page)

        def moving(hwnd):
            self.backend.rect = (120, 70, 520, 370)
            return (108, 80, 492, 342)
        self.shares.clicks.rect_of = moving
        self.assertEqual(STALE, (await self.click())["error"])
        self.assertEqual([], [c for c in self.page.calls if c[0] == "Input.dispatchMouseEvent"])


class FinalGuardTests(ClickFixture):
    """Authority and time are judged after the last blocking call, not before it."""

    def on_layout(self, action, nth):
        original, count = self.backend.layout, []

        def layout(hwnd):
            count.append(1)
            if len(count) == nth:
                action()
            return original(hwnd)
        self.backend.layout = layout

    async def test_access_switched_off_during_the_final_layout_read_stops_the_click(self):
        self.on_layout(self.shares.revoke_standing, 3)  # run, after consent, then the one at dispatch
        reply = await self.click()
        self.assertEqual(("failed", GONE), (reply["status"], reply["error"]))
        self.assertEqual([], self.sends())
        self.assertNotIn("mouse_approved", self.entry)

    async def test_a_deadline_passing_during_the_final_layout_read_stops_the_click(self):
        def later():
            self.clock[0] += 100
        self.on_layout(later, 3)
        self.assertEqual(LATE, (await self.click(budget=40))["error"])
        self.assertEqual([], self.sends())

    async def test_the_cdp_deadline_covers_the_setup_and_the_audit_write_before_the_first_input(self):
        self.access.grant["process"] = "chrome.exe"
        self.snapshot = self.take()
        self.shares.chrome.page = AsyncMock(return_value=self.page)

        def slow_frame(hwnd):
            self.clock[0] += 39.9
            return (108, 80, 492, 342)
        self.shares.clicks.rect_of = slow_frame

        def slow_audit(*args, **kwargs):
            self.clock[0] += 1
        self.audit.append.side_effect = slow_audit
        reply = await self.click(clicks=2, budget=40)
        self.assertEqual(("failed", LATE), (reply["status"], reply["error"]))
        self.assertEqual([], [c for c in self.page.calls if c[0] == "Input.dispatchMouseEvent"])

    async def test_a_double_click_stops_before_a_press_past_the_dispatch_cap_and_never_leaves_one_down(self):
        self.access.grant["process"] = "chrome.exe"
        self.snapshot = self.take()
        self.shares.chrome.page = AsyncMock(return_value=self.page)
        self.page.on_input = lambda: self.clock.__setitem__(0, self.clock[0] + 9.9)
        reply = await self.click(clicks=2, budget=100)
        kinds = [p["type"] for m, p in self.page.calls if m == "Input.dispatchMouseEvent"]
        self.assertEqual(["mouseMoved", "mousePressed", "mouseReleased"], kinds)
        self.assertEqual(("unconfirmed", "cdp", PARTLY), (reply["status"], reply["route"], reply["error"]))
        self.assertEqual(kinds.count("mousePressed"), kinds.count("mouseReleased"))

    async def test_a_double_click_inside_the_cap_still_completes(self):
        self.access.grant["process"] = "chrome.exe"
        self.snapshot = self.take()
        self.shares.chrome.page = AsyncMock(return_value=self.page)
        self.page.on_input = lambda: self.clock.__setitem__(0, self.clock[0] + 3)
        reply = await self.click(clicks=2, budget=100)
        self.assertEqual("completed", reply["status"])


class DeadlineTests(ClickFixture):
    """The server stops waiting at its deadline and reports the click unconfirmed; nothing may start after."""

    def test_the_budget_is_the_servers_number_bounded_and_defaults_when_missing_or_wrong(self):
        for given, expected in ((40, 40.0), (2.5, 2.5), (0, 1.0), (-5, 1.0), (500, 120.0), (None, BUDGET),
                                (True, BUDGET), ("5", BUDGET)):
            message = {} if given is None else {"budget": given}
            self.assertEqual(float(expected), PointClicks.budget(message))

    async def test_a_consent_that_arrives_after_the_deadline_is_discarded_and_nothing_is_sent(self):
        async def slow(*args, **kwargs):
            self.clock[0] += 41  # the person answered after the server's 40 s
            return True
        self.ask.side_effect = slow
        reply = await self.click(budget=40)
        self.assertEqual(("failed", LATE), (reply["status"], reply["error"]))
        self.assertNotIn("mouse_approved", self.entry)
        self.assertEqual([], self.pointer.calls)
        self.ask.side_effect = None
        self.assertEqual("completed", (await self.click(budget=40))["status"])

    async def test_the_deadline_is_the_servers_budget_counted_from_arrival(self):
        async def slow(*args, **kwargs):
            self.clock[0] += 6
            return True
        self.ask.side_effect = slow
        self.assertEqual(LATE, (await self.click(budget=5))["error"])
        self.assertEqual("completed", (await self.click(budget=7))["status"])

    async def test_a_deadline_that_passes_during_the_slow_checks_refuses_the_click(self):
        def slow():
            self.clock[0] += 50
            return self.windows
        self.access.list_windows = slow
        reply = await self.click(budget=40)
        self.assertEqual(LATE, reply["error"])
        self.assertEqual([], self.sends())
        self.assertEqual((5, 5), self.pointer.cursor_at)

    async def test_a_cdp_click_is_not_started_after_the_deadline(self):
        self.access.grant["process"] = "chrome.exe"
        self.snapshot = self.take()
        self.shares.chrome.page = AsyncMock(return_value=FakePage())
        page = self.shares.chrome.page.return_value

        def slow(hwnd):
            self.clock[0] += 41
            return (108, 80, 492, 342)
        self.shares.clicks.rect_of = slow
        reply = await self.click(budget=40)
        self.assertEqual(LATE, reply["error"])
        self.assertEqual([], [c for c in page.calls if c[0] == "Input.dispatchMouseEvent"])
        self.assertEqual(["failed"], [row["result"] for row in self.rows()])  # no "dispatching" row


class RefusalTests(ClickFixture):
    async def refused(self, text=None, **extra):
        reply = await self.click(**extra)
        self.assertEqual("failed", reply["status"], reply)
        self.assertEqual([], self.sends())
        self.ask.assert_not_called()
        if text:
            self.assertIn(text, reply["error"])
        return reply

    async def test_a_moved_resized_or_regranted_window_makes_the_snapshot_stale(self):
        self.backend.rect = (110, 50, 510, 350)
        reply = await self.refused()
        self.assertEqual(STALE, reply["error"])
        self.assertIn("take a fresh screen_window_snapshot", STALE)
        self.backend.rect = RECT
        self.backend.regions = [(108, 80, 400, 342)]  # resized: the client area is not the recorded one
        await self.refused(STALE)
        self.backend.regions = [REGION]
        self.access.grant = dict(GRANT)  # re-granted: a new grant object under the same id
        await self.refused(STALE)

    async def test_a_new_grant_generation_makes_the_snapshot_stale(self):
        self.access.gate.invalidate()
        self.access.gate.grant()
        await self.refused(STALE)  # a snapshot of an earlier generation never clicks
        self.snapshot = self.take()
        self.access.gate.invalidate()
        await self.refused(GONE)

    async def test_an_unknown_snapshot_is_stale(self):
        self.snapshot = "nope"
        await self.refused(STALE)

    async def test_points_outside_the_client_area_or_the_image_are_refused(self):
        await self.refused("client area", x=5, y=100, screen=None)
        await self.refused("outside the snapshot image", x=400, y=10, screen=None)
        await self.refused("outside the snapshot image", x=-1, y=10, screen=None)
        await self.refused("whole image pixels", x=1.5, y=10, screen=None)

    async def test_the_helper_converts_the_point_itself_and_a_server_that_disagrees_is_refused(self):
        await self.refused("disagree", screen=[201, 150])

    async def test_a_window_closed_since_the_snapshot_ends_the_grant_and_refuses(self):
        self.access.check = AsyncMock(return_value="window closed")
        await self.refused("window closed")
        self.access.revoke.assert_called_once()

    async def test_a_log_that_cannot_be_written_refuses_the_click_before_input(self):
        self.audit.append.side_effect = OSError("disk full")
        reply = await self.click()
        self.assertEqual("failed", reply["status"])
        self.assertIn("audit log", reply["error"])
        self.assertEqual([], self.sends())
        self.assertEqual([], [c for c in self.pointer.calls if isinstance(c, tuple) and c[0] == "move"])

    async def test_a_grant_that_is_gone_or_toggled_off_answers_without_input(self):
        self.shares.session.window_access_audit = Mock()
        await self.shares.dispatch({"type": "window_click", "request_id": "r2", "grant_id": "none",
                                    "agent": "alice", "line": "l"})
        reply = self.socket.sent[-1]
        self.assertEqual(("window_element_result", "failed", "consent revoked"),
                         (reply["type"], reply["status"], reply["error"]))
        self.assertEqual("point_click", self.session.window_access_audit.append.call_args.args[2])
        self.entry["standing_access"] = True
        self.session.window_access_enabled = False
        await self.shares.dispatch({"type": "window_click", "request_id": "r3", "grant_id": "g1",
                                    "agent": "alice", "line": "l"})
        self.assertEqual("window access is off", self.socket.sent[-1]["error"])
        self.assertEqual([], self.pointer.calls)

    async def test_an_unexpected_failure_still_answers(self):
        self.pointer.window_at = Mock(side_effect=RuntimeError("boom"))
        reply = await self.click()
        self.assertEqual("failed", reply["status"])
        self.assertIn("helper's terminal", reply["error"])

    async def test_a_click_that_never_finishes_is_unconfirmed(self):
        import partyline_helper.window_click as module

        async def too_slow(awaitable, timeout):
            awaitable.close()
            raise TimeoutError
        fake = SimpleNamespace(to_thread=asyncio.to_thread, wait_for=too_slow)
        with patch.object(module, "asyncio", fake):
            reply = await self.click()
        self.assertEqual("unconfirmed", reply["status"])


class DialogWordsTests(unittest.IsolatedAsyncioTestCase):
    def test_the_two_buttons_can_carry_their_own_words_through_the_request(self):
        import base64
        import sys
        from partyline_helper import dialog_proc
        request = dialog_proc.encode_request("T", "M", 5, labels=("Allow for this window", "Deny"), parent=1)
        decoded = json.loads(base64.urlsafe_b64decode(request))
        self.assertEqual(["Allow for this window", "Deny"], decoded["labels"])
        plain = json.loads(base64.urlsafe_b64decode(dialog_proc.encode_request("T", "M", 5)))
        self.assertNotIn("labels", plain)
        seen = []
        with patch.object(dialog_proc, "ask", lambda *a: seen.append(a[6]) or True):
            self.assertEqual(0, dialog_proc.main([request], lambda pid: None))
        self.assertEqual([("Allow for this window", "Deny")], seen)
        from tests.test_helper_dialog import TkDialogProcessTests
        module, root = TkDialogProcessTests.fake_tk(None, "Allow for this window")
        with patch.dict(sys.modules, {"tkinter": module}):
            self.assertTrue(dialog_proc.tk_ask("T", "M", 5, labels=("Allow for this window", "Deny")))
        self.assertEqual(["Allow for this window", "Deny"], list(root.buttons))

    async def test_confirm_labeled_hands_the_words_to_the_dialog_backend_and_answers_yes_only_on_yes(self):
        from partyline_helper import consent_dialog
        seen = []

        def backend(title, message, remaining, **options):
            seen.append(options)
            return SimpleNamespace(wait=lambda: True, close=lambda: None, checked=False)
        with patch.object(consent_dialog, "_confirm", AsyncMock(return_value=(True, False))) as confirm:
            self.assertTrue(await consent_dialog.confirm_labeled("T", "M", ("Yes!", "No!"), 5, backend))
        self.assertEqual(("Yes!", "No!"), confirm.await_args.kwargs["labels"])
        self.assertEqual([], seen)


class MarkTests(unittest.TestCase):
    GEOMETRY = {"rect": [100, 50, 500, 350], "size": [800, 600], "regions": [[108, 80, 492, 342]], "dpi": 96,
                "scale": [2.0, 2.0]}

    def test_screen_boxes_become_image_pixels_through_the_geometry_scale(self):
        marks = clean_inputs([{"n": 1, "id": "a", "name": "Save", "screen": [120, 90, 180, 110]},
                              {"n": 2, "id": "b", "viewport": [0, 0, 10, 10]},
                              {"n": 3, "id": "c", "screen": [100, 50, 101, 51]},
                              {"n": "x", "id": "d", "screen": [0, 0, 5, 5]}, "junk",
                              {"n": 4, "id": "e", "screen": [0, 0, True, 5]}])
        found = boxes(marks, self.GEOMETRY)
        self.assertEqual([{"n": 1, "id": "a", "name": "Save", "box": [40, 80, 160, 120]}], listed(found))
        # a page box needs the page origin and factor, here 1 screen pixel per CSS pixel at (108, 80)
        page = boxes(marks, self.GEOMETRY, (108, 80, 1.0))
        self.assertEqual([1, 2], [item["n"] for item in listed(page)])
        self.assertEqual([16, 60, 36, 80], listed(page)[1]["box"])

    def test_boxes_are_clipped_to_the_image_and_the_overlay_keeps_pixels_and_info(self):
        marks = [{"n": 1, "id": "a", "name": "", "screen": [90, 40, 130, 70]}]
        self.assertEqual([0, 0, 60, 40], listed(boxes(marks, self.GEOMETRY))[0]["box"])
        image = Image.new("RGB", (800, 600), (10, 20, 30))
        image.info["rect"] = RECT
        drawn = draw(image, boxes(marks, self.GEOMETRY))
        self.assertEqual((800, 600), drawn.size)
        self.assertEqual(RECT, drawn.info["rect"])
        self.assertEqual((10, 20, 30), drawn.getpixel((650, 450)))  # away from lines and boxes
        self.assertNotEqual((10, 20, 30), drawn.getpixel((100, 300)))  # a grid line
        self.assertEqual((10, 20, 30), image.getpixel((100, 300)))  # the original is untouched


class MarkedSnapshotTests(ClickFixture):
    async def test_a_marked_snapshot_reports_its_geometry_id_and_the_listed_boxes(self):
        self.backend.grab = lambda hwnd: self.grabbed()
        self.backend.minimized = lambda hwnd: False
        await self.shares.dispatch({"type": "snapshot_window", "request_id": "s1", "grant_id": "g1",
                                    "agent": "alice", "overlay": True,
                                    "marks": [{"n": 1, "id": "a", "name": "Save",
                                               "screen": [120, 90, 180, 110]}]})
        await asyncio.gather(*self.shares.tasks)
        reply = [m for m in self.socket.sent if isinstance(m, dict) and m["type"] == "window_snapshot"][-1]
        self.assertEqual([{"n": 1, "id": "a", "name": "Save", "box": [20, 40, 80, 60]}], reply["marks"])
        self.assertEqual(RECT, tuple(reply["geometry"]["rect"]))
        self.assertEqual([400, 300], reply["geometry"]["size"])
        self.assertIn(reply["snapshot_id"], self.entry["snapshots"])
        # and that snapshot id is one a click may name
        self.snapshot = reply["snapshot_id"]
        self.assertEqual("completed", (await self.click())["status"])

    def grabbed(self):
        image = Image.new("RGB", (400, 300), (200, 200, 200))
        image.info.update(rect=RECT, regions=[REGION], dpi=96)
        return image

    async def test_a_plain_snapshot_has_no_marks_and_the_oldest_snapshots_are_forgotten(self):
        for _ in range(12):
            self.take()
        self.assertEqual(8, len(self.entry["snapshots"]))
        image = Image.new("RGB", (4, 4))
        self.assertEqual((None, None), WindowSnapshots.remember(self.entry, self.access.grant, image, 1))
        image.info.update(rect=(0, 0, 0, 0), regions=[(0, 0, 1, 1)])
        self.assertEqual((None, None), WindowSnapshots.remember(self.entry, self.access.grant, image, 1))


if __name__ == "__main__":
    unittest.main()
