"""Window outline stacking uses a fake user32 z-order list; nothing touches a desktop or a clock."""
import queue
import unittest
from unittest.mock import Mock, patch

from partyline_helper.border_native import TkBackend, windows_options
from partyline_helper.window_outline import (
    EVENT_OBJECT_REORDER, EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MINIMIZESTART,
    WindowOutline, WindowOutlineEvents,
)
from partyline_helper.window_zorder import (
    HWND_NOTOPMOST, HWND_TOP, HWND_TOPMOST, PLACE_FLAGS, next_command, place_above,
)

TARGET, STRIPS = 100, [201, 202]


class FakeUser32:
    """A top-to-bottom z-order list with GetWindow(GW_HWNDPREV) and SetWindowPos(insert-after)."""

    def __init__(self, order, topmost=()):
        self.order, self.topmost = list(order), set(topmost)
        self.calls = []
        self.IsWindow = Mock(return_value=True)
        self.GetWindow = Mock(side_effect=self.get_window)
        self.GetWindowLongPtrW = Mock(side_effect=lambda hwnd, _index: 8 if hwnd in self.topmost else 0)
        self.SetWindowPos = Mock(side_effect=self.set_window_pos)

    def get_window(self, hwnd, relation):
        assert relation == 3
        index = self.order.index(hwnd)
        return self.order[index - 1] if index else None

    def set_window_pos(self, hwnd, after, x, y, width, height, flags):
        self.calls.append((hwnd, after, flags))
        index = self.order.index(hwnd)
        self.order.remove(hwnd)
        if after == HWND_TOPMOST:
            self.topmost.add(hwnd)
            self.order.insert(0, hwnd)
        elif after == HWND_NOTOPMOST:
            if hwnd in self.topmost:
                self.topmost.discard(hwnd)
                self.order.insert(len([h for h in self.order if h in self.topmost]), hwnd)
            else:
                self.order.insert(index, hwnd)  # documented no-op for a non-topmost window
        elif after == HWND_TOP:  # top of the window's own band
            self.order.insert(0 if hwnd in self.topmost else len(self.topmost & set(self.order)), hwnd)
        else:
            (self.topmost.add if after in self.topmost else self.topmost.discard)(hwnd)
            self.order.insert(self.order.index(after) + 1, hwnd)


class PlaceAboveTests(unittest.TestCase):
    def test_strips_sit_directly_above_target_below_windows_in_front(self):
        user32 = FakeUser32([900, 800, TARGET, 50, 201, 202])
        self.assertTrue(place_above(user32, TARGET, STRIPS))
        self.assertEqual(user32.order, [900, 800, 202, 201, TARGET, 50])
        for _, after, flags in user32.calls:
            self.assertEqual(after, 800)
            self.assertEqual(flags, PLACE_FLAGS)
            self.assertTrue(flags & 0x0010)  # SWP_NOACTIVATE
            self.assertFalse(flags & 0x0040)  # never SWP_SHOWWINDOW
        self.assertNotIn(TARGET, [call[0] for call in user32.calls])

    def test_game_in_front_stays_in_front_after_foreground_change(self):
        user32 = FakeUser32([900, TARGET, 201, 202])  # the target was just raised over its strips
        place_above(user32, TARGET, STRIPS)
        self.assertEqual(user32.order[0], 900)
        self.assertEqual(user32.order[-1], TARGET)

    def test_no_call_when_already_directly_above_target(self):
        user32 = FakeUser32([900, 202, 201, TARGET, 50])
        self.assertFalse(place_above(user32, TARGET, STRIPS))
        user32.SetWindowPos.assert_not_called()

    def test_partial_run_and_target_at_top(self):
        user32 = FakeUser32([201, 900, 202, TARGET])
        self.assertTrue(place_above(user32, TARGET, STRIPS))
        self.assertEqual(user32.order[-1], TARGET)
        self.assertEqual(set(user32.order[-3:-1]), set(STRIPS))
        user32 = FakeUser32([TARGET, 50, 201, 202])
        place_above(user32, TARGET, STRIPS)
        self.assertEqual(user32.order, [202, 201, TARGET, 50])
        self.assertEqual({call[1] for call in user32.calls}, {HWND_TOP})
        self.assertEqual(user32.topmost, set())

    def test_topmost_windows_in_front_never_make_the_outline_topmost(self):
        user32 = FakeUser32([700, TARGET, 201, 202], topmost={700})
        place_above(user32, TARGET, STRIPS)
        self.assertEqual({call[1] for call in user32.calls}, {HWND_TOP})
        self.assertEqual(user32.order, [700, 202, 201, TARGET])
        self.assertEqual(user32.topmost, {700})

    def test_topmost_target_keeps_outline_with_it(self):
        user32 = FakeUser32([TARGET, 201, 202], topmost={TARGET})
        place_above(user32, TARGET, STRIPS)
        self.assertEqual({call[1] for call in user32.calls}, {HWND_TOPMOST})
        self.assertEqual(user32.order, [202, 201, TARGET])
        user32 = FakeUser32([700, TARGET, 201, 202], topmost={700, TARGET})
        place_above(user32, TARGET, STRIPS)
        self.assertEqual(user32.order, [700, 202, 201, TARGET])

    def test_strips_follow_target_out_of_the_topmost_band(self):
        user32 = FakeUser32([202, 201, TARGET, 50], topmost={201, 202})
        self.assertTrue(place_above(user32, TARGET, STRIPS))
        self.assertEqual(user32.topmost, set())
        self.assertEqual(user32.order, [202, 201, TARGET, 50])
        self.assertEqual([call[1] for call in user32.calls[:2]], [HWND_NOTOPMOST] * 2)
        user32.SetWindowPos.reset_mock()
        self.assertFalse(place_above(user32, TARGET, STRIPS))
        user32.SetWindowPos.assert_not_called()

    def test_gone_target_or_no_strips_is_a_no_op(self):
        user32 = FakeUser32([TARGET, 201])
        user32.IsWindow.return_value = False
        self.assertFalse(place_above(user32, TARGET, STRIPS))
        self.assertFalse(place_above(FakeUser32([TARGET]), TARGET, []))
        user32.SetWindowPos.assert_not_called()


class CommandTests(unittest.TestCase):
    @staticmethod
    def queued(*commands):
        queue_ = queue.Queue()
        for command in commands:
            queue_.put(command)
        return queue_

    def test_place_never_replaces_a_pending_show_or_hide(self):
        show, hide = ("show", [(0, 0, 5, 3)], "#4a90e2"), ("hide",)
        self.assertEqual(next_command(self.queued(show, ("place",)), 0), (show, True))
        self.assertEqual(next_command(self.queued(("place",), show), 0), (show, True))
        self.assertEqual(next_command(self.queued(show, ("place",), hide), 0), (hide, True))
        self.assertEqual(next_command(self.queued(("place",)), 0), ((None,), True))
        self.assertEqual(next_command(self.queued(), 0), ((None,), False))
        self.assertEqual(next_command(self.queued(show, ("close",), hide), 0), (("close",), False))

    def test_queued_show_then_place_still_creates_every_strip_and_seats_once(self):
        tk = Mock()
        backend = TkBackend(Mock(), windows=True, above=TARGET)
        for command in (("show", [(0, 0, 5, 3), (0, 9, 5, 3)], "#4a90e2"), ("place",)):
            backend.commands.put(command)
        tk.Tk.return_value.update.side_effect = lambda: backend.commands.put(("close",))
        with patch.dict("sys.modules", {"tkinter": tk}), patch.object(backend, "make_window") as make, \
                patch.object(backend, "seat") as seat:
            backend.run()
        self.assertEqual(make.call_count, 2)
        seat.assert_called_once()


class OutlineNativeTests(unittest.TestCase):
    def test_outline_window_is_not_topmost_but_stays_click_through_and_excluded(self):
        window = Mock()
        window.winfo_id.return_value = 77
        windll = Mock()
        windll.user32.GetAncestor.return_value = 888
        windll.user32.GetWindowLongPtrW.return_value = 0
        windows_options(window, windll, build=19041, topmost=False)
        style = windll.user32.SetWindowLongPtrW.call_args.args[2]
        self.assertFalse(style & 0x00000008)  # WS_EX_TOPMOST
        for flag in (0x00080000, 0x00000020, 0x00000080, 0x08000000):
            self.assertTrue(style & flag)
        windll.user32.SetWindowPos.assert_not_called()
        windll.user32.SetWindowDisplayAffinity.assert_called_once_with(888, 0x11)

    def test_monitor_border_default_stays_topmost(self):
        windll = Mock()
        windll.user32.GetWindowLongPtrW.return_value = 0
        windows_options(Mock(), windll, build=19041)
        self.assertTrue(windll.user32.SetWindowLongPtrW.call_args.args[2] & 0x8)
        self.assertEqual(windll.user32.SetWindowPos.call_args.args[1], -1)

    def test_tk_strips_skip_tk_topmost_only_when_seated_above_a_window(self):
        tk = Mock()
        with patch("partyline_helper.border_native.windows_options") as options:
            TkBackend(Mock(), windows=True, above=TARGET).make_window(tk, Mock(), (0, 0, 10, 3), "#4a90e2")
            options.assert_called_once_with(tk.Toplevel.return_value, topmost=False)
            tk.Toplevel.return_value.attributes.assert_not_called()
            TkBackend(Mock(), windows=True).make_window(tk, Mock(), (0, 0, 10, 3), "#f6c344")
            tk.Toplevel.return_value.attributes.assert_called_once_with("-topmost", True)

    def test_backend_place_is_queued_for_the_gui_thread_only_for_outlines(self):
        backend = TkBackend(Mock(), windows=True, above=TARGET)
        backend.place()
        self.assertTrue(backend.commands.empty())  # not started
        backend.thread = Mock()
        backend.place()
        self.assertEqual(backend.commands.get_nowait(), ("place",))
        border = TkBackend(Mock(), windows=True)
        border.thread = Mock()
        border.place()
        self.assertTrue(border.commands.empty())

    def test_seat_uses_each_strips_root_window(self):
        user32 = FakeUser32([TARGET, 201, 202])
        user32.GetAncestor = Mock(side_effect=lambda child, _flag: child + 100)
        strips = [Mock(), Mock()]
        strips[0].winfo_id.return_value, strips[1].winfo_id.return_value = 101, 102
        TkBackend(Mock(), windows=True, above=TARGET, user32=user32).seat(strips)
        self.assertEqual(user32.order, [202, 201, TARGET])


class OutlineEventTests(unittest.TestCase):
    def make(self):
        backend = Mock()
        outline = WindowOutline(TARGET, backend_factory=lambda _: backend, user32=Mock(), dwmapi=Mock())
        outline.backend = backend
        return outline, backend

    def test_foreground_and_reorder_of_any_window_replace_the_strips(self):
        outline, backend = self.make()
        outline.handle_event(EVENT_SYSTEM_FOREGROUND, 555)
        outline.handle_event(EVENT_OBJECT_REORDER, 0, 0)
        self.assertEqual(backend.place.call_count, 2)
        backend.show.assert_not_called()

    def test_no_replace_while_hidden_or_closed(self):
        outline, backend = self.make()
        outline.handle_event(EVENT_SYSTEM_MINIMIZESTART, TARGET)
        outline.handle_event(EVENT_SYSTEM_FOREGROUND, 555)
        backend.place.assert_not_called()
        outline.hidden, outline.closed = False, True
        outline.handle_event(EVENT_OBJECT_REORDER, 555)
        backend.place.assert_not_called()

    def test_hook_listens_for_z_order_events_from_any_window(self):
        self.assertIn(EVENT_SYSTEM_FOREGROUND, WindowOutlineEvents.EVENTS)
        self.assertIn(EVENT_OBJECT_REORDER, WindowOutlineEvents.EVENTS)
        changed = Mock()
        events = WindowOutlineEvents(TARGET, changed, Mock(), user32=Mock())
        events.dispatch(EVENT_SYSTEM_FOREGROUND, 555, 0, 0)
        events.dispatch(EVENT_OBJECT_REORDER, 556, -4, 0)
        self.assertEqual(changed.call_count, 2)

    def test_z_order_hooks_are_global_while_window_hooks_keep_the_process_filter(self):
        events = WindowOutlineEvents(TARGET, Mock(), Mock(), user32=Mock(), pid=42)
        self.assertEqual(events.hook_pid(EVENT_SYSTEM_FOREGROUND), 0)
        self.assertEqual(events.hook_pid(EVENT_OBJECT_REORDER), 0)
        self.assertEqual(events.hook_pid(EVENT_SYSTEM_MINIMIZESTART), 42)
        self.assertEqual(WindowOutlineEvents(TARGET, Mock(), Mock()).hook_pid(EVENT_SYSTEM_MINIMIZESTART), 0)

    def test_default_backend_seats_above_the_granted_window(self):
        outline = WindowOutline(TARGET, user32=Mock(), dwmapi=Mock())
        with patch("partyline_helper.window_outline.TkBackend") as backend:
            outline.backend_factory(Mock())
        self.assertEqual(backend.call_args.kwargs, {"windows": True, "above": TARGET})


if __name__ == "__main__":
    unittest.main()
