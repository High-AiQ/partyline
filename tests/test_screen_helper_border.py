"""Capture-zone border tests use fake backends and never create native windows."""
import asyncio
import ctypes
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline_helper import cli, desktop
from partyline_helper.border import BORDER_THICKNESS, MODE_COLORS, CaptureBorder, outside_strips
from partyline_helper.border_native import (
    TkBackend, XErrorEvent, cocoa_frame, windows_options, x11_click_through,
)
from partyline_helper.client import Session
from tests.screen_helper_fakes import FakeDesktop, FakeSocket, FakeTerminal, ManualTime, request


class FakeBorder:
    def __init__(self):
        self.shown = []
        self.hidden = 0

    def show(self, region):
        self.shown.append(region.copy())

    def hide(self):
        self.hidden += 1


class GeometryTests(unittest.TestCase):
    def test_strips_are_outside_negative_origin_and_scaled(self):
        region = dict(x=-100, y=20, width=200, height=100)
        self.assertEqual(BORDER_THICKNESS, 4)
        self.assertEqual(outside_strips(region), [
            (-104, 16, 208, 4), (-104, 120, 208, 4),
            (-104, 20, 4, 100), (100, 20, 4, 100),
        ])
        scaled = outside_strips(region, scale=2)
        self.assertEqual(scaled, [
            (-52, 8, 104, 2), (-52, 60, 104, 2),
            (-52, 10, 2, 50), (50, 10, 2, 50),
        ])
        self.assertEqual(cocoa_frame(scaled[0], 900), (-52, 890, 104, 2))
        with self.assertRaises(ValueError):
            outside_strips(region, scale=0)


class BorderTests(unittest.TestCase):
    def test_show_hide_and_control_mode(self):
        backend = Mock()
        border = CaptureBorder(scale=2, backend_factory=lambda on_error: backend)
        region = dict(x=-100, y=20, width=200, height=100)
        border.show(region)
        backend.show.assert_called_once_with(outside_strips(region, scale=2), MODE_COLORS["share"])
        border.set_mode("control")
        self.assertEqual(backend.show.call_args.args[1], MODE_COLORS["control"])
        with self.assertRaises(ValueError):
            border.set_mode("unknown")
        border.hide()
        backend.hide.assert_called_once_with()
        border.close()
        border.close()
        backend.close.assert_called_once_with()

    def test_factory_and_backend_failures_warn_once_and_fail_open(self):
        warnings = []
        border = CaptureBorder(backend_factory=Mock(side_effect=RuntimeError("no display\nsecond line")),
                               warning=warnings.append)
        border.show(request()["region"])
        border.show(request()["region"])
        border.hide()
        border.close()
        self.assertEqual(warnings, ["Capture border unavailable; sharing continues: no display second line"])

        backend = Mock()
        backend.show.side_effect = OSError("cannot draw")
        border = CaptureBorder(backend_factory=lambda on_error: backend, warning=warnings.append)
        border.show(request()["region"])
        border.hide()
        border.close()
        self.assertEqual(len(warnings), 2)

    def test_mac_without_pyobjc_degrades_through_public_border(self):
        warnings = []
        with patch("partyline_helper.border_native.sys.platform", "darwin"), \
                patch.dict("sys.modules", {"AppKit": None}):
            border = CaptureBorder(warning=warnings.append)
            border.show(request()["region"])
        self.assertIn("needs PyObjC", warnings[0])


class TkLifetimeTests(unittest.TestCase):
    def test_owner_thread_collects_interpreter_cycles_on_close_and_failure(self):
        for drawing_fails in (False, True):
            with self.subTest(drawing_fails=drawing_fails):
                root = Mock()
                fake_tk = SimpleNamespace(Tk=Mock(return_value=root))
                errors = []
                backend = TkBackend(errors.append)
                command = ("show", [(-104, -4, 208, 4)], "#f6c344") if drawing_fails else ("close",)
                backend.commands.put(command)
                collections = []
                with patch.dict("sys.modules", {"tkinter": fake_tk}), \
                        patch("partyline_helper.border_native.gc.collect",
                              side_effect=lambda collections=collections: collections.append(
                                  threading.get_ident())), \
                        patch.object(backend, "make_window", side_effect=RuntimeError("draw failed")):
                    backend.run_safe()
                expected_collections = 2 if drawing_fails else 1
                self.assertEqual(collections, [threading.get_ident()] * expected_collections)
                root.destroy.assert_called()
                if drawing_fails:
                    self.assertEqual(len(errors), 1)


class X11Tests(unittest.TestCase):
    def test_empty_input_shape_and_display_cleanup(self):
        window = Mock()
        window.winfo_id.return_value = 9
        x11, xext = Mock(), Mock()
        x11.XOpenDisplay.return_value = 123
        x11_click_through(window, x11, xext)
        window.update_idletasks.assert_called_once_with()
        xext.XShapeCombineRectangles.assert_called_once_with(123, 9, 2, 0, 0, None, 0, 0, 0)
        self.assertEqual(len(xext.XShapeCombineRectangles.argtypes), 9)
        x11.XSync.assert_called_once_with(123, False)
        x11.XCloseDisplay.assert_called_once_with(123)
        self.assertEqual(x11.XSetErrorHandler.call_count, 2)
        x11.XOpenDisplay.return_value = 0
        with self.assertRaisesRegex(OSError, "click-through"):
            x11_click_through(window, x11, xext)

    def test_native_x_errors_become_fail_open_exceptions(self):
        window = Mock()
        x11, xext = Mock(), Mock()
        x11.XOpenDisplay.return_value = 123
        handlers = []
        x11.XSetErrorHandler.side_effect = lambda handler: handlers.append(handler) or 0
        event = XErrorEvent(error_code=3)
        handler_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(XErrorEvent))

        def synchronize(display, discard):
            ctypes.cast(handlers[0], handler_type)(display, ctypes.byref(event))

        x11.XSync.side_effect = synchronize
        with self.assertRaisesRegex(OSError, "error 3"):
            x11_click_through(window, x11, xext)
        x11.XCloseDisplay.assert_called_once_with(123)
        self.assertEqual(x11.XSetErrorHandler.call_count, 2)

    def test_tk_geometry_preserves_absolute_negative_coordinates(self):
        tk = Mock()
        window = tk.Toplevel.return_value
        with patch("partyline_helper.border_native.x11_click_through"):
            TkBackend(Mock()).make_window(tk, Mock(), (-104, -4, 208, 4), "#f6c344")
        window.geometry.assert_called_once_with("208x4+-104+-4")


class WindowsTests(unittest.TestCase):
    def test_hidden_wrapper_exists_before_windows_options(self):
        tk = Mock()
        window = tk.Toplevel.return_value
        events = []
        window.update_idletasks.side_effect = lambda: events.append("idle")
        with patch("partyline_helper.border_native.windows_options",
                   side_effect=lambda native: events.append("options")):
            TkBackend(Mock(), windows=True).make_window(tk, Mock(), (10, 10, 100, 4), "#f6c344")
        self.assertEqual(events, ["idle", "options"])

    def test_click_through_topmost_and_capture_affinity(self):
        window = Mock()
        window.winfo_id.return_value = 77
        windll = Mock()
        windll.user32.GetAncestor.return_value = 888
        windll.user32.GetWindowLongPtrW.return_value = 0
        windows_options(window, windll, build=19041)
        windll.user32.GetAncestor.assert_called_once_with(77, 2)
        style = windll.user32.SetWindowLongPtrW.call_args.args[2]
        for flag in (0x00080000, 0x00000020, 0x00000080, 0x00000008, 0x08000000):
            self.assertTrue(style & flag)
        windll.user32.SetLayeredWindowAttributes.assert_called_once_with(888, 0, 255, 2)
        windll.user32.SetWindowPos.assert_called_once()
        windll.user32.SetWindowDisplayAffinity.assert_called_once_with(888, 0x11)

    def test_old_windows_skips_affinity_and_refusal_fails_open_at_border(self):
        windll = Mock()
        windll.user32.GetWindowLongPtrW.return_value = 0
        windows_options(Mock(), windll, build=19040)
        windll.user32.SetWindowDisplayAffinity.assert_not_called()
        windll.user32.SetWindowDisplayAffinity.return_value = 0
        with self.assertRaisesRegex(OSError, "exclude the border"):
            windows_options(Mock(), windll, build=19041)

    def test_layered_opacity_must_be_initialized(self):
        windll = Mock()
        windll.user32.GetWindowLongPtrW.return_value = 0
        windll.user32.SetLayeredWindowAttributes.return_value = 0
        with self.assertRaisesRegex(OSError, "layered capture border"):
            windows_options(Mock(), windll, build=19041)
        windll.user32.SetWindowDisplayAffinity.assert_not_called()


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.desktop = FakeDesktop()
        self.terminal = FakeTerminal()
        self.socket = FakeSocket()
        self.clock = ManualTime()
        self.border = FakeBorder()
        self.session = Session(self.socket, self.desktop, self.terminal, "desktop",
                               clock=self.clock, sleep=self.clock.sleep, border=self.border)

    async def asyncTearDown(self):
        await self.session.stop(notify=False)

    async def accepted(self):
        await self.session.dispatch(request())
        await self.socket.next("frame")
        await self.terminal.waiting.get()
        self.assertEqual(self.border.shown[-1], request()["region"])

    async def test_remote_and_local_stop_hide(self):
        await self.accepted()
        await self.session.dispatch(dict(type="stop_share", share_id="share"))
        await self.socket.next("share_stopped")
        self.assertGreaterEqual(self.border.hidden, 1)
        await self.accepted()
        await self.terminal.lines.put("s")
        stopped = await self.socket.next("share_stopped")
        self.assertEqual(stopped["reason"], "local")
        self.assertGreaterEqual(self.border.hidden, 2)

    async def test_capture_exception_hides_and_sharing_end_is_reported(self):
        with patch.object(self.desktop, "grab", side_effect=RuntimeError("capture failed")):
            await self.session.start(request())
        self.assertEqual(self.border.shown, [request()["region"]])
        self.assertEqual(self.border.hidden, 1)
        self.assertEqual(self.socket.sent[-1]["type"], "share_stopped")

    async def test_disconnect_and_ctrl_c_hide(self):
        class Socket(FakeSocket):
            def __aiter__(self):
                return self

            async def __anext__(self):
                await self.closed_event.wait()
                raise StopAsyncIteration

        self.socket = Socket()
        self.session = Session(self.socket, self.desktop, self.terminal, "desktop",
                               clock=self.clock, sleep=self.clock.sleep, border=self.border)
        running = asyncio.create_task(self.session.run())
        await self.socket.next("hello")
        await self.accepted()
        await self.socket.close()
        await running
        self.assertGreaterEqual(self.border.hidden, 1)

        self.socket.closed_event.clear()
        self.socket.close_code = 1000
        running = asyncio.create_task(self.session.run())
        await self.socket.next("hello")
        await self.accepted()
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertGreaterEqual(self.border.hidden, 2)


class CliBorderTests(unittest.TestCase):
    def test_no_border_skips_backend_and_default_closes_it(self):
        fake_desktop = Mock(scale=1)
        with patch.object(desktop, "Desktop", return_value=fake_desktop), \
                patch.object(cli, "load_config", return_value={}), \
                patch("partyline_helper.terminal.Terminal"), \
                patch("partyline_helper.links.claim_run", return_value=True), \
                patch("partyline_helper.client.serve", new=AsyncMock()) as serving, \
                patch("partyline_helper.border.CaptureBorder") as border_type:
            cli.main(["run", "--no-border"])
            border_type.assert_not_called()
            self.assertIsNone(serving.call_args.kwargs["border"])
            cli.main(["run"])
            border_type.assert_called_once_with(scale=1)
            self.assertIs(serving.call_args.kwargs["border"], border_type.return_value)
            border_type.return_value.close.assert_called_once_with()
