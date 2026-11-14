"""Window outlines consume native event and DWM fakes; no desktop or delays are used."""
import ctypes
import threading
import unittest
from ctypes import wintypes as w
from unittest.mock import Mock, patch

from partyline_helper.border import MODE_COLORS
from partyline_helper.window_outline import (
    EVENT_OBJECT_CLOAKED, EVENT_OBJECT_DESTROY, EVENT_OBJECT_LOCATIONCHANGE,
    EVENT_OBJECT_UNCLOAKED, EVENT_SYSTEM_MINIMIZEEND, EVENT_SYSTEM_MINIMIZESTART,
    OUTLINE_COLOR, WindowOutline, WindowOutlineEvents,
)


class NativeFakes:
    def __init__(self, rect=(10, 20, 210, 120)):
        self.rect = w.RECT(*rect)
        self.user32 = Mock()
        self.user32.IsIconic.return_value = False
        self.dwmapi = Mock()
        def bounds(hwnd, attr, output, size):
            if attr == 9:
                ctypes.memmove(output, ctypes.byref(self.rect), size)
            else:
                ctypes.cast(output, ctypes.POINTER(w.DWORD)).contents.value = 0
            return 0
        self.dwmapi.DwmGetWindowAttribute.side_effect = bounds


class OutlineTests(unittest.IsolatedAsyncioTestCase):
    def make(self, rect=(10, 20, 210, 120)):
        native = NativeFakes(rect)
        backend = Mock()
        outline = WindowOutline(7, pid=42, backend_factory=lambda _: backend,
                                user32=native.user32, dwmapi=native.dwmapi)
        return outline, native, backend

    def test_initial_frame_uses_dwm_extended_bounds_and_blue_mode(self):
        outline, native, backend = self.make((100, 200, 500, 450))
        outline.update()
        rectangles, color = backend.show.call_args.args
        self.assertEqual(color, MODE_COLORS["window"])
        self.assertEqual(color, OUTLINE_COLOR)
        self.assertEqual(rectangles, [(97, 197, 406, 3), (97, 450, 406, 3),
                                      (97, 200, 3, 250), (500, 200, 3, 250)])
        self.assertEqual(native.dwmapi.DwmGetWindowAttribute.call_count, 2)
        self.assertEqual([call.args[1] for call in native.dwmapi.DwmGetWindowAttribute.call_args_list],
                         [9, 14])

    def test_location_changes_follow_moves_and_resizes(self):
        outline, native, backend = self.make()
        outline.update()
        native.rect = w.RECT(-100, 40, 300, 240)
        outline.handle_event(EVENT_OBJECT_LOCATIONCHANGE, 7)
        rects, _ = backend.show.call_args.args
        self.assertEqual(rects[0], (-103, 37, 406, 3))
        self.assertEqual(rects[2], (-103, 40, 3, 200))

    def test_minimize_and_cloak_hide_then_restore(self):
        for start, end in ((EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND),
                           (EVENT_OBJECT_CLOAKED, EVENT_OBJECT_UNCLOAKED)):
            with self.subTest(start=start):
                outline, _, backend = self.make()
                outline.update()
                outline.handle_event(start, 7)
                backend.hide.assert_called_once()
                shown = backend.show.call_count
                outline.handle_event(EVENT_OBJECT_LOCATIONCHANGE, 7)
                self.assertEqual(shown, backend.show.call_count)
                outline.handle_event(end, 7)
                self.assertEqual(shown + 1, backend.show.call_count)

    def test_minimized_initial_window_is_hidden_and_wrong_hwnd_is_ignored(self):
        outline, native, backend = self.make()
        native.user32.IsIconic.return_value = True
        outline.update()
        backend.show.assert_not_called()
        outline.handle_event(EVENT_SYSTEM_MINIMIZESTART, 8)
        backend.hide.assert_not_called()

    def test_initial_cloak_is_hidden_using_dwm_state(self):
        outline, native, backend = self.make()
        def cloaked(hwnd, attr, output, size):
            if attr == 14:
                ctypes.cast(output, ctypes.POINTER(w.DWORD)).contents.value = 1
            else:
                ctypes.memmove(output, ctypes.byref(native.rect), size)
            return 0
        native.dwmapi.DwmGetWindowAttribute.side_effect = cloaked
        outline.update()
        backend.show.assert_not_called()

    def test_destroy_hides_and_close_ends_outline(self):
        outline, _, backend = self.make()
        outline.update()
        outline.handle_event(EVENT_OBJECT_DESTROY, 7)
        backend.hide.assert_called_once()
        outline.close()
        backend.close.assert_called_once()
        outline.update()
        self.assertEqual(1, backend.show.call_count)

    def test_close_during_frame_update_prevents_backend_creation(self):
        outline, _, _ = self.make()
        factory = Mock()
        outline.backend_factory = factory
        outline.frame_bounds = lambda: (outline.close(), (10, 20, 200, 100))[1]
        outline.update()
        self.assertTrue(outline.closed)
        factory.assert_not_called()

    def test_concurrent_updates_share_backend_and_close_serializes_after_show(self):
        outline, _, _ = self.make()
        entered, release = threading.Event(), threading.Event()
        backend = Mock()
        created = []
        def make_backend(_error):
            created.append(backend)
            entered.set()
            release.wait()
            return backend
        outline.backend_factory = make_backend
        first = threading.Thread(target=outline.update)
        second_started = threading.Event()
        def update_second():
            second_started.set()
            outline.update()
        second = threading.Thread(target=update_second)
        first.start()
        entered.wait()
        second.start()
        second_started.wait()
        release.set()
        first.join()
        second.join()
        outline.close()
        self.assertEqual([backend], created)
        self.assertGreater(backend.show.call_count, 0)
        backend.close.assert_called_once()

    def test_native_window_requests_capture_exclusion(self):
        from partyline_helper.border_native import windows_options
        window = Mock()
        window.winfo_id.return_value = 77
        windll = Mock()
        windll.user32.GetAncestor.return_value = 888
        windll.user32.GetWindowLongPtrW.return_value = 0
        windows_options(window, windll, build=19041)
        windll.user32.SetWindowDisplayAffinity.assert_called_once_with(888, 0x11)

    def test_event_callback_filters_to_granted_window_and_object(self):
        changed = Mock()
        events = WindowOutlineEvents(7, changed, Mock(), user32=Mock())
        callback = events.EVENTS
        self.assertIn(EVENT_OBJECT_LOCATIONCHANGE, callback)
        events.dispatch(EVENT_OBJECT_LOCATIONCHANGE, 8, 0, 0)
        events.dispatch(EVENT_OBJECT_LOCATIONCHANGE, 7, 1, 0)
        changed.assert_not_called()
        events.dispatch(EVENT_OBJECT_LOCATIONCHANGE, 7, 0, 0)
        changed.assert_called_once_with(EVENT_OBJECT_LOCATIONCHANGE, 7, 0)

    async def test_start_draws_initial_outline_and_starts_native_events(self):
        outline, _, backend = self.make()
        outline.pid = 42
        with patch("partyline_helper.window_outline.sys.platform", "win32"), \
                patch("partyline_helper.window_outline.WindowOutlineEvents") as events:
            await outline.start()
        self.assertEqual(1, backend.show.call_count)
        events.assert_called_once()
        self.assertEqual(events.call_args.kwargs["pid"], 42)
        events.return_value.start.assert_called_once()
        outline.close()
        events.return_value.close.assert_called_once()
