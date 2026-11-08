"""Helper-side agent control: consent, confinement and the kill switch, with fake input only."""
import asyncio
import contextlib
import io
import sys
import types
import unittest
from unittest.mock import Mock, patch

from partyline_helper import acting, actions, cli, control, inputs, keys
from partyline_helper.border import MODE_COLORS, CaptureBorder
from partyline_helper.client import Session
from partyline_helper.terminal import Terminal
from tests.screen_helper_fakes import (
    AutoTime, FakeDesktop, FakeInputs, FakeSocket, FakeTerminal, ManualTime, checkpoint, request,
)

ASK = dict(type="control_request", share_id="share", requested_by="agent-x", line_name="line")


def act(kind, **fields):
    return dict(type="action", share_id="share", request_id=f"r-{kind}", action=dict(kind=kind, **fields))


class ControlSessionTests(unittest.IsolatedAsyncioTestCase):
    def make(self, clock=None, **kwargs):
        self.desktop, self.terminal, self.socket = FakeDesktop(), FakeTerminal(), FakeSocket()
        self.clock = clock or ManualTime()
        self.inputs = FakeInputs(self.desktop, kwargs.pop("fail", None))
        self.out = io.StringIO()
        self.session = Session(self.socket, self.desktop, self.terminal, "desktop", clock=self.clock,
                               sleep=self.clock.sleep, inputs=self.inputs, **kwargs)

    async def asyncSetUp(self):
        self.make()

    async def remake(self, **kwargs):
        await self.session.stop(notify=False)
        self.make(**kwargs)

    async def asyncTearDown(self):
        await self.session.stop(notify=False)

    async def share(self):
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(request())
            await self.socket.next("frame")
            await self.terminal.waiting.get()

    async def grant(self, armed=True):
        """Grant control. Takeback detection arms on the agent's first action, so most tests arm it here
        (as if the agent had already acted); the ones about the unarmed window pass armed=False."""
        self.terminal.control_answer = True
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(ASK)
            granted = await self.socket.next("control_granted")
        if armed:
            self.session.control.armed, self.session.control.target = True, self.desktop.position
        return granted

    async def result(self, message):
        with contextlib.redirect_stdout(self.out):  # the action prints from its own task
            await self.session.dispatch(message)
            return await self.socket.next("action_result")

    async def test_decline_then_grant_with_indicator_and_red_border(self):
        backend = Mock()
        await self.remake(border=CaptureBorder(backend_factory=lambda on_error: backend))

        def colors():
            return [call.args[1] for call in backend.show.call_args_list]
        await self.share()
        self.assertEqual(colors(), [MODE_COLORS["share"]])
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(ASK)
            declined = await self.socket.next("control_revoked")
        self.assertEqual(await self.terminal.asks.get(), "Allow agent control? [y/N] ")
        title, message = self.terminal.dialogs[0]  # the same question when there is no terminal
        self.assertEqual(title, "Partyline agent control request")
        self.assertIn("agent-x asks to control the mouse and keyboard", message)
        self.assertIn("declined", declined["reason"])
        self.assertIn("Requested by: agent-x", self.out.getvalue())
        self.assertEqual(colors(), [MODE_COLORS["share"]])
        await self.grant()
        self.assertIn("AGENT CONTROL ACTIVE", self.out.getvalue())
        self.assertEqual(colors()[-1], MODE_COLORS["control"])
        await self.grant()  # a repeated request answers granted without asking again
        self.assertEqual(self.terminal.asks.qsize(), 1)
        self.inputs.on_key("a", False, True)
        await checkpoint()
        self.assertEqual(colors()[-1], MODE_COLORS["share"])
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(dict(type="stop_share", share_id="share"))
            await self.socket.next("share_stopped")
        await self.share()  # a new share needs a new grant
        await self.grant()
        self.assertEqual(colors()[-2:], [MODE_COLORS["share"], MODE_COLORS["control"]])
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(dict(type="stop_share", share_id="share"))
            await self.socket.next("share_stopped")
        self.assertEqual(colors()[-1], MODE_COLORS["share"])  # ending while red resets to amber
        self.assertGreaterEqual(backend.hide.call_count, 2)

    async def test_yes_never_grants_control(self):
        await self.remake(yes=True)
        await self.share()
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(ASK)
            revoked = await self.socket.next("control_revoked")
        self.assertEqual(self.terminal.asks.qsize(), 1)
        self.assertIn("declined", revoked["reason"])
        self.assertFalse(self.session.control.granted)

    async def test_without_prompt_flag_grants_loudly(self):
        await self.remake(allow_control=True)
        await self.share()
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(ASK)
            await self.socket.next("control_granted")
        self.assertTrue(self.terminal.asks.empty())
        self.assertIn("WARNING: --allow-control-without-prompt", self.out.getvalue())

    async def test_requests_without_share_or_pending_prompt(self):
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(ASK)
        self.assertEqual((await self.socket.next("control_revoked"))["reason"], "no active share")
        await self.share()
        self.terminal.control_answer = asyncio.get_running_loop().create_future()
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(ASK)
            await self.terminal.asks.get()
            self.assertTrue(self.session.control.prompting)
            await self.session.dispatch(ASK)
            self.assertEqual((await self.socket.next("control_revoked"))["reason"], "prompt pending")
            # Partyline withdraws the request: the prompt is cancelled and the share stays revoked.
            await self.session.dispatch(dict(type="control_revoked", share_id="share", reason="person"))
            await checkpoint()
            self.assertFalse(self.session.control.prompting)
            await self.session.dispatch(ASK)
        self.assertIn("already revoked", (await self.socket.next("control_revoked"))["reason"])

    async def test_listener_failure_fails_closed(self):
        for failure in ("listen", "init"):
            await self.remake(fail=failure)
            await self.share()
            self.terminal.control_answer = True
            with contextlib.redirect_stdout(self.out):
                await self.session.dispatch(ASK)
                revoked = await self.socket.next("control_revoked")
            self.assertIn("control unavailable", revoked["reason"])
            self.assertFalse(self.session.control.granted)

    async def test_confined_actions_and_post_action_frame(self):
        await self.remake(clock=AutoTime())
        await self.share()
        await self.grant()
        self.socket.messages["frame"] = asyncio.Queue()
        refused = await self.result(act("type", text="hi"))
        self.assertIn("click inside the shared region first", refused["error"])
        outside = await self.result(act("click", x=100, y=10))  # region spans x -100..99
        self.assertFalse(outside["ok"])
        self.assertIn("outside the shared region", outside["error"])
        clicked = await self.result(act("click", x=-100, y=99, button="right", double=True))
        self.assertTrue(clicked["ok"])
        self.assertEqual(clicked["pointer"], dict(x=-100, y=99))
        frame = await self.socket.next("frame")
        self.assertEqual(frame["request_id"], "r-click")
        self.assertEqual(self.inputs.calls[-2:], [("move", -100, 99), ("click", "right", 2)])
        for message, call in ((act("type", text="hello\n"), ("type", "\n")),
                              (act("key", keys="Ctrl+S"), ("key", ("ctrl", "s"))),
                              (act("scroll", x=0, y=0, dx=0, dy=-3), ("scroll", 0, -3)),
                              (act("move", x=5, y=6), ("move", 5, 6))):
            self.assertTrue((await self.result(message))["ok"], message)
            self.assertEqual(self.inputs.calls[-1], call)
        self.assertEqual("".join(call[1] for call in self.inputs.calls if call[0] == "type"), "hello\n")
        self.assertTrue((await self.result(act("drag", x1=-50, y1=10, x2=50, y2=90)))["ok"])
        self.assertEqual(self.inputs.calls[-13:-11], [("move", -50, 10), ("press", "left")])
        self.assertEqual(self.inputs.calls[-2:], [("move", 50, 90), ("release", "left")])
        before = len(self.inputs.calls)
        with patch("partyline_helper.acting.platform.system", return_value="Windows"):
            for combo in ("ctrl+alt+del", "win+l", "Ctrl+Alt+Shift+Delete", "ctrl+alt+esc"):
                self.assertIn("blocked", (await self.result(act("key", keys=combo)))["error"])
        for bad in (act("type", text="x" * 501), act("scroll", x=0, y=0, dx=0, dy=0),
                    act("click", x=0, y=0, button="side"), act("teleport"), act("move", x=1.5, y=2),
                    dict(act("move"), action="nope")):
            self.assertFalse((await self.result(bad))["ok"], bad)
        self.assertEqual(len(self.inputs.calls), before)
        self.assertIn("Agent agent-x: drag", self.out.getvalue())

    async def test_local_rate_ceiling(self):
        await self.share()
        await self.grant()
        control_ = self.session.control
        with contextlib.redirect_stdout(self.out):
            await control_.perform(act("move", x=1, y=1))
            with self.assertRaisesRegex(ValueError, "rate limit"):
                await control_.perform(act("move", x=2, y=2))
            self.clock.advance(acting.MIN_INTERVAL)
            await control_.perform(act("move", x=2, y=2))

    async def queue_two_moves(self):
        """The first move pauses in its settle; the second waits in the queue behind it."""
        await self.share()
        await self.grant()
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(act("move", x=1, y=1))
            await self.session.dispatch(dict(act("move", x=2, y=2), request_id="r-second"))
            self.assertTrue((await self.socket.next("action_result"))["ok"])
        self.assertEqual(len(self.session.control.pending), 1)

    async def test_revoke_and_stop_discard_queued_actions(self):
        for stop in (dict(type="control_revoked", share_id="share", reason="person"),
                     dict(type="stop_share", share_id="share")):
            await self.remake()
            await self.queue_two_moves()
            with contextlib.redirect_stdout(self.out):
                await self.session.dispatch(stop)  # the receive loop is free: handled at once
            self.assertFalse(self.session.control.granted)
            second = await self.socket.next("action_result")
            self.assertEqual((second["request_id"], second["ok"], second["started"]),
                             ("r-second", False, False))
            self.assertIn("discarded", second["error"])
            with contextlib.redirect_stdout(self.out):
                self.clock.advance(acting.SETTLE)
                await checkpoint()
                await checkpoint()
            self.assertEqual([call for call in self.inputs.calls if call[0] == "move"], [("move", 1, 1)])

    async def test_pointer_drift_revokes_for_the_share(self):
        await self.share()
        await self.grant()
        self.desktop.position = (-20 + control.DRIFT, 30)  # within tolerance
        self.clock.advance(control.WATCH)
        await checkpoint()
        self.assertTrue(self.session.control.granted)
        self.desktop.position = (60, 60)
        self.clock.advance(control.WATCH)
        revoked = await self.socket.next("control_revoked")
        self.assertIn("pointer was moved", revoked["reason"])
        self.assertIn("revoked", (await self.result(act("move", x=1, y=1)))["error"])
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(ASK)
        self.assertIn("already revoked", (await self.socket.next("control_revoked"))["reason"])
        self.assertTrue(self.inputs.stopped)

    async def test_the_person_may_move_and_type_after_the_dialog_until_the_agent_acts(self):
        """Greg clicked Yes in the dialog and moved the mouse away: that must not revoke control."""
        await self.share()
        await self.grant(armed=False)
        control_ = self.session.control
        self.assertFalse(control_.armed)
        self.desktop.position = (400, 400)  # far from the Yes button
        self.clock.advance(control.WATCH)
        self.inputs.on_key("q", False, True)  # the person types too
        self.inputs.on_key("q", False, False)
        await checkpoint()
        self.assertTrue(control_.granted)
        self.assertFalse(control_.drifted())

    async def test_the_first_action_baselines_from_the_agents_point_not_the_grant_pointer(self):
        await self.share()
        await self.grant(armed=False)
        self.desktop.position = (400, 400)  # where the person left the mouse
        control_ = self.session.control
        self.assertTrue((await self.result(act("move", x=10, y=10)))["ok"])
        self.assertTrue(control_.armed and control_.granted)
        self.assertEqual(control_.target, (10, 10))
        self.desktop.position = (10, 10)  # the fake pointer follows the agent's injected move
        self.clock.advance(control.WATCH)
        await checkpoint()
        self.assertTrue(control_.granted)

    async def test_drift_and_keys_after_the_first_action_revoke(self):
        await self.share()
        await self.grant(armed=False)
        await self.result(act("move", x=10, y=10))
        self.desktop.position = (200, 200)
        self.clock.advance(control.WATCH)
        revoked = await self.socket.next("control_revoked")
        self.assertIn("pointer was moved", revoked["reason"])
        await self.remake()
        await self.share()
        await self.grant(armed=False)
        await self.result(act("move", x=10, y=10))
        self.inputs.on_key("q", False, True)
        self.assertIn("key was pressed", (await self.socket.next("control_revoked"))["reason"])

    async def test_ctrl_alt_esc_revokes_before_the_agent_has_acted(self):
        await self.share()
        await self.grant(armed=False)
        for key in ("ctrl", "alt", "esc"):
            self.inputs.on_key(key, False, True)
        revoked = await self.socket.next("control_revoked")
        self.assertEqual(revoked["reason"], "Ctrl+Alt+Esc pressed")
        self.assertFalse(self.session.control.granted)

    async def test_consent_distinguishes_element_actions_from_mouse_takeback(self):
        await self.share()
        await self.grant(armed=False)
        message = self.terminal.dialogs[0][1]
        self.assertIn("After mouse or keyboard control starts", message)
        self.assertIn("Window grants have separate Stop controls", message)
        self.assertIn("Ctrl+Alt+Esc", message)

    async def test_drift_is_checked_before_each_action(self):
        await self.share()
        await self.grant()
        self.desktop.position = (90, 90)
        refused = await self.result(act("move", x=1, y=1))
        self.assertIn("pointer was moved", refused["error"])
        await self.socket.next("control_revoked")

    async def test_key_presses_and_hotkey(self):
        await self.share()
        await self.grant()
        self.inputs.on_key("a", True, True)  # injected: the agent's own key
        self.inputs.on_key("x", False, False)  # a release alone is no press
        await checkpoint()
        self.assertTrue(self.session.control.granted)
        self.session.control.flags_injected = False  # X11: the hotkey still wins over expected keys
        self.session.control.expect(["ctrl", "alt"])
        self.inputs.on_key("ctrl", False, True)
        self.inputs.on_key("alt", False, True)
        self.inputs.on_key("esc", False, True)
        revoked = await self.socket.next("control_revoked")
        self.assertEqual(revoked["reason"], "Ctrl+Alt+Esc pressed")
        await self.remake()
        await self.share()
        await self.grant()
        self.inputs.on_key("q", False, True)
        self.assertIn("key was pressed", (await self.socket.next("control_revoked"))["reason"])

    async def clicked(self, flags_injected):
        await self.remake(clock=AutoTime())
        await self.share()
        await self.grant()
        self.session.control.flags_injected = flags_injected
        self.session.control.watcher.cancel()  # keys only: its AutoTime polling would race the clock
        self.assertTrue((await self.result(act("click", x=0, y=0)))["ok"])

    async def typed_hello(self, flags_injected):
        await self.clicked(flags_injected)
        self.assertTrue((await self.result(act("type", text="hello")))["ok"])

    async def revoked_by_key(self):
        reason = (await self.socket.next("control_revoked"))["reason"]
        self.assertEqual(reason, "a key was pressed on the computer")
        self.assertFalse(self.session.control.granted)

    async def test_physical_keys_after_typing_revoke(self):
        for flags_injected in (True, False):
            await self.typed_hello(flags_injected)
            self.inputs.on_key("q", False, True)  # straight after typing
            await self.revoked_by_key()
        await self.typed_hello(True)  # Windows/macOS: an unflagged copy of a typed key is still physical
        self.inputs.on_key("h", False, True)
        await self.revoked_by_key()

    async def test_physical_key_during_typing_stops_the_text(self):
        for flags_injected in (True, False):
            await self.typed_hello(flags_injected)
            self.inputs.on_type = lambda char: char == "b" and self.inputs.on_key("z", False, True)
            interrupted = await self.result(act("type", text="abcdef"))
            self.assertEqual((interrupted["ok"], interrupted["started"]), (False, True))
            self.assertIn("after 2 of 6 characters", interrupted["error"])
            await self.revoked_by_key()
        self.assertEqual(acting.xtest_echoes(["ctrl", "shift", "s"]), ["ctrl", "shift"])

    async def x11(self, order):
        await self.clicked(False)
        self.inputs.x11 = order

    async def still_granted(self):
        await checkpoint()
        self.assertTrue(self.session.control.granted)

    async def test_x11_text_carries_shift_in_its_state(self):
        for order in ("notice-first", "echo-first"):
            for text, physical in (("Ab", "shift"), ("Hi!?", "shift"), ("hello", "h"), (" ", "space")):
                await self.x11(order)
                self.assertTrue((await self.result(act("type", text=text)))["ok"])
                await self.still_granted()
                self.inputs.on_key(physical, False, True)  # no phantom expectation hides it
                await self.revoked_by_key()

    async def test_x11_named_keys_echo_once_in_either_order(self):
        for order in ("notice-first", "echo-first"):
            for message, physical in ((act("key", keys="enter"), "enter"),
                                      (act("type", text="a\n\tb"), "tab"),
                                      (act("key", keys="ctrl+shift+s"), "ctrl"),
                                      (act("key", keys="shift+tab"), "tab")):  # echo: ISO_Left_Tab
                await self.x11(order)
                self.assertTrue((await self.result(message))["ok"], message)
                await self.still_granted()  # the flagged notice and the unflagged XTest echo
                self.inputs.on_key(physical, False, True)  # the echo was used: this one is the person's
                await self.revoked_by_key()
        await self.clicked(False)  # an echo that never came lapses after QUIET
        self.assertTrue((await self.result(act("key", keys="enter")))["ok"])
        self.clock.advance(acting.QUIET)
        self.inputs.on_key("enter", False, True)
        await self.revoked_by_key()

    async def test_runner_failures_never_strand_requests(self):
        await self.queue_two_moves()
        frame = self.session.frame

        async def capture_fails(*args, **kwargs):
            self.session.frame = frame
            raise RuntimeError("capture broke")
        self.session.frame = capture_fails
        with contextlib.redirect_stdout(self.out):
            self.clock.advance(acting.SETTLE)
            error = await self.socket.next("error")
            self.assertEqual((error["request_id"], error["message"]),
                             ("r-move", "capture failed: capture broke"))
            second = await self.socket.next("action_result")  # the queue carries on
        self.assertEqual((second["request_id"], second["ok"]), ("r-second", True))
        self.inputs.move = Mock(side_effect=OSError("XTest gone"))
        with contextlib.redirect_stdout(self.out):
            self.clock.advance(acting.SETTLE)
            await self.session.dispatch(dict(act("move", x=3, y=3), request_id="r-third"))
            await self.session.dispatch(dict(act("move", x=4, y=4), request_id="r-fourth"))
            results = [await self.socket.next("action_result") for _ in range(2)]
            revoked = await self.socket.next("control_revoked")
        by_id = {item["request_id"]: item for item in results}
        self.assertEqual((by_id["r-third"]["ok"], by_id["r-third"]["started"]), (False, True))
        self.assertIn("failed: XTest gone", by_id["r-third"]["error"])
        self.assertIn("discarded", by_id["r-fourth"]["error"])
        self.assertIn("agent control failed", revoked["reason"])
        self.assertFalse(self.session.control.granted)
        self.assertTrue(self.session.control.runner.done())

    async def test_interrupted_drag_reports_that_it_started(self):
        await self.remake(clock=AutoTime())
        await self.share()
        await self.grant()
        self.inputs.on_key("q", False, True)
        drag = act("drag", x1=0, y1=0, x2=50, y2=50)
        refused = await self.result(drag)  # revoked before it began: nothing was injected
        self.assertEqual((refused["ok"], refused["started"]), (False, False))
        await self.remake(clock=AutoTime())
        await self.share()
        await self.grant()
        original = self.session.sleep

        async def drift_mid_drag(delay):
            if delay == acting.DRAG_STEP and len(self.inputs.calls) > 3:
                self.desktop.position = (90, 90)
            await original(delay)
        self.session.sleep = drift_mid_drag
        interrupted = await self.result(drag)
        self.assertEqual((interrupted["ok"], interrupted["started"]), (False, True))
        self.assertEqual(self.inputs.calls[-1], ("release", "left"))

    async def test_control_ends_with_share_local_stop_and_disconnect(self):
        await self.share()
        await self.grant()
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(dict(type="stop_share", share_id="share"))
        self.assertFalse(self.session.control.granted)
        self.assertTrue(self.inputs.stopped)
        self.assertIn("Agent control ended", self.out.getvalue())
        await self.remake()
        await self.share()
        await self.grant()
        with contextlib.redirect_stdout(self.out):
            await self.terminal.lines.put("s")
            await self.socket.next("share_stopped")
        await checkpoint()
        self.assertFalse(self.session.control.granted)
        await self.remake()
        await self.share()
        await self.grant()
        with contextlib.redirect_stdout(self.out):
            await self.session.stop("disconnected")
        self.assertFalse(self.session.control.granted)
        self.assertIn("not granted", (await self.result(act("move", x=1, y=1)))["error"])

    async def test_share_start_control_and_unsupported_messages(self):
        self.terminal.control_answer = True
        with contextlib.redirect_stdout(self.out):
            await self.session.dispatch(request(control=True))
            await self.socket.next("control_granted")
            await self.session.dispatch(dict(type="mystery", request_id="m"))
        self.assertEqual((await self.socket.next("error"))["message"], "unsupported: mystery")


class PureHelperTests(unittest.TestCase):
    def test_parse_and_blocklist(self):
        self.assertEqual(keys.parse("Shift+CMD+z"), ("shift", "meta", "z"))
        self.assertEqual(keys.parse("return"), ("enter",))
        self.assertEqual(keys.parse("win"), ("meta",))
        for bad in ("", "ctrl+", "ctrl+ctrl+a", "a+b", "ctrl+banana", None, "x" * 65):
            with self.assertRaises(ValueError, msg=bad):
                keys.parse(bad)
        self.assertTrue(keys.blocked(keys.parse("ctrl+alt+del"), "Darwin"))
        self.assertTrue(keys.blocked(keys.parse("super+l"), "Linux"))
        self.assertFalse(keys.blocked(keys.parse("cmd+l"), "Darwin"))  # browser address bar
        self.assertTrue(keys.blocked(keys.parse("ctrl+cmd+q"), "Darwin"))
        self.assertTrue(keys.blocked(keys.parse("win+l"), "SomethingElse"))
        self.assertFalse(keys.blocked(keys.parse("alt+tab"), "Windows"))

    def test_validate_points(self):
        region = dict(x=-1920, y=-200, width=1920, height=1080)
        self.assertEqual(actions.validate(dict(kind="move", x=-1920, y=879), region, "Windows")["at"],
                         (-1920, 879))
        for x, y in ((0, 0), (-1921, 0), (-5, -201), (-5, 880)):
            with self.assertRaises(ValueError):
                actions.validate(dict(kind="move", x=x, y=y), region, "Windows")
        with self.assertRaises(ValueError):
            actions.validate(dict(kind="drag", x1=-5, y1=0, x2=5, y2=0), region, "Windows")
        with self.assertRaises(ValueError):
            actions.validate(dict(kind="key", keys="win+l"), region, "Windows")


class FakePynput:
    def __init__(self):
        Key = types.SimpleNamespace(cmd="CMD", enter="ENTER", ctrl="CTRL")
        self.positions, self.events = [], []
        events = self.events

        class Mouse:
            @property
            def position(self):
                return (0, 0)

            @position.setter
            def position(inner, value):
                self.positions.append(value)

            def press(self, button):
                events.append(("press", button))

            def release(self, button):
                events.append(("release", button))

            def click(self, button, count):
                events.append(("click", button, count))

            def scroll(self, dx, dy):
                events.append(("scroll", dx, dy))

        class Keyboard:
            def type(self, text):
                events.append(("type", text))

            def press(self, key):
                events.append(("down", key))

            def release(self, key):
                events.append(("up", key))

        class Listener:
            IS_TRUSTED = True

            def __init__(self, on_press, on_release):
                self.on_press, self.on_release, self.alive = on_press, on_release, False

            def start(self):
                self.alive = True

            def wait(self):
                pass

            def is_alive(self):
                return self.alive

            def stop(self):
                self.alive = False

        self.mouse = types.SimpleNamespace(Controller=Mouse, Button=types.SimpleNamespace(
            left="LEFT", right="RIGHT", middle="MIDDLE"))
        self.keyboard = types.SimpleNamespace(Controller=Keyboard, Key=Key, Listener=Listener)
        self.package = types.SimpleNamespace(mouse=self.mouse, keyboard=self.keyboard)


class InputsTests(unittest.TestCase):
    def test_pynput_backend_inverts_desktop_pointer(self):
        fake = FakePynput()
        with patch.dict(sys.modules, {"pynput": fake.package, "pynput.mouse": fake.mouse,
                                      "pynput.keyboard": fake.keyboard}):
            backend = inputs.Inputs(scale=2.0)
            backend.move(200, 100)
            # The darwin setter takes CG top-left points: backing pixels / scale, no Y offset.
            self.assertEqual(fake.positions, [(100.0, 50.0)])
            backend.press("left")
            backend.release("left")
            backend.click("middle", 2)
            backend.scroll(1, -2)
            backend.type("hi")
            backend.key(("ctrl", "meta", "s"))
            self.assertEqual(fake.events[-6:], [("down", "CTRL"), ("down", "CMD"), ("down", "s"),
                                                ("up", "s"), ("up", "CMD"), ("up", "CTRL")])
            with self.assertRaises(ValueError):
                backend.key(("f13",))
            seen = []
            backend.listen(lambda *event: seen.append(event))
            backend.listener.on_press(types.SimpleNamespace(name="ctrl_l"), False)
            backend.listener.on_release(types.SimpleNamespace(name=None, char="Q"), True)
            self.assertEqual(seen, [("ctrl", False, True), ("q", True, False)])
            backend.stop()
            backend.stop()
            fake.keyboard.Listener.IS_TRUSTED = False
            with self.assertRaises(RuntimeError):
                backend.listen(lambda *event: None)
        self.assertEqual(inputs.key_name(types.SimpleNamespace(name="cmd_r")), "meta")
        self.assertEqual(inputs.key_name(types.SimpleNamespace(name="alt_gr")), "alt")
        self.assertEqual(inputs.key_name(types.SimpleNamespace(name=None, char=None)), "unknown")
        # X11 Shift+Tab reads back as ISO_Left_Tab, an unnamed KeyCode: still tab, both ways.
        self.assertEqual(inputs.key_name(types.SimpleNamespace(name=None, char=None, vk=0xFE20)), "tab")
        self.assertEqual(inputs.key_name(types.SimpleNamespace(name=None, char=None, vk=0xFE21)), "unknown")

    def test_mac_permission_guard(self):
        services = Mock()
        services.AXIsProcessTrusted.return_value = False
        with patch.object(inputs.sys, "platform", "darwin"), \
                patch.object(inputs.ctypes, "CDLL", return_value=services):
            self.assertFalse(inputs.trusted())
            with self.assertRaisesRegex(RuntimeError, "Accessibility"):
                inputs.Inputs()
        self.assertTrue(inputs.trusted())

    def test_default_inputs_uses_desktop_scale(self):
        with patch("partyline_helper.inputs.Inputs") as backend:
            control.default_inputs(types.SimpleNamespace(scale=2.0, pointer_y_offset=5))
        backend.assert_called_once_with(2.0)


class TerminalAskTests(unittest.IsolatedAsyncioTestCase):
    async def test_guarded_prompt_ignores_early_input_and_times_out(self):
        clock = ManualTime()
        term = Terminal(clock=clock, sleep=clock.sleep, read_stdin=False)
        with contextlib.redirect_stdout(io.StringIO()):
            asking = asyncio.create_task(term.ask("Allow agent control? [y/N] "))
            self.assertEqual(await clock.sleep_calls.get(), 1)
            term.lines.put("y")  # typed during the guard: discarded
            clock.advance(1)
            await clock.sleep_calls.get()
            clock.advance(59)
            self.assertFalse(await asking)
            asking = asyncio.create_task(term.ask("Allow agent control? [y/N] "))
            await clock.sleep_calls.get()
            clock.advance(1)
            await clock.sleep_calls.get()
            term.lines.put("y")
            clock.advance(.05)
            self.assertTrue(await asking)


    async def test_without_a_terminal_the_dialog_asks(self):
        clock = ManualTime()
        dialog = Mock(side_effect=lambda *args, **kwargs: asyncio.sleep(0, result=True))
        term = Terminal(clock=clock, sleep=clock.sleep, read_stdin=False, dialog=dialog)
        self.assertTrue(await term.ask("Allow agent control? [y/N] ", dialog=("Title", "Body")))
        dialog.assert_called_once_with("Title", "Body", timeout=60, sleep=clock.sleep)


class CliControlFlagTests(unittest.TestCase):
    def test_flags(self):
        for argv, allowed in ((["run", "--yes"], False), (["run", "--allow-control-without-prompt"], True)):
            out = io.StringIO()
            with patch("partyline_helper.desktop.Desktop"), \
                    patch.object(cli, "load_config", return_value={}), \
                    patch("partyline_helper.client.serve", new=Mock()) as serving, \
                    patch("partyline_helper.terminal.Terminal"), \
                    patch.object(cli.asyncio, "run", side_effect=lambda work: work.close()), \
                    patch("partyline_helper.links.claim_run", return_value=True), \
                    patch("partyline_helper.border.CaptureBorder"), \
                    contextlib.redirect_stdout(out):
                cli.main(argv)
            self.assertEqual(serving.call_args.kwargs["allow_control"], allowed)
            self.assertEqual("WITHOUT ASKING" in out.getvalue(), allowed)
