"""Capture frame delivery reacts only to injected FrameArrived and close events."""

import asyncio
import ctypes
import sys
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from ctypes import wintypes
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

from PIL import Image

from partyline.file_events import Changes
from partyline_helper import desktop as desktop_module
from partyline_helper.capture_loop import _WindowsCapture, capture
from partyline_helper.windows_capture import window_for_region
from tests.screen_helper_fakes import checkpoint


# Native smoke bounds: failure deadlines only, never waited out when capture works.
FIRST_FRAME_MS = 5000
STOP_S = 2


class FakeCaptureSession:
    def __init__(self, request):
        self.request = request
        self.stopped = False

    def start(self, on_frame, on_closed):
        self.on_frame, self.on_closed = on_frame, on_closed

    def frame(self, color="red"):
        self.on_frame(Image.new("RGB", (20, 10), color), (0, 0))

    def close_window(self):
        self.on_closed()

    def stop(self):
        self.stopped = True


class FakeTerminal:
    def __init__(self):
        self.input = asyncio.Queue()

    async def read(self, _timeout):
        return await self.input.get()


class FakeShare:
    def __init__(self, request):
        self.share = request
        self.accepted = True
        self.pending_id = request["share_id"]
        self.control = type("Control", (), {"input_changes": Changes(), "prompting": False,
                                             "end": Mock()})()
        self.terminal = FakeTerminal()
        self.frames = []
        self.frame_event = asyncio.Event()
        self.send = AsyncMock()

    async def frame_from_capture(self, request, image):
        if self.share is request and self.accepted:
            self.frames.append(image.copy())
            self.frame_event.set()


class FakeClock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


class FakeWgcFrameBuffer:
    def tobytes(self):
        # Two pixels in BGR order: red, then green.
        return bytes((0, 0, 255, 0, 255, 0))


class FakeWgcFrame:
    width = 2
    height = 1
    frame_buffer = FakeWgcFrameBuffer()

    def convert_to_bgr(self):
        return self


class FakeCaptureControl:
    def __init__(self):
        self.stop_count = 0
        self.wait_count = 0

    def stop(self):
        self.stop_count += 1

    def wait(self):
        self.wait_count += 1


class StrictFakeWindowsCapture:
    """Match windows-capture's name-based event decorator contract."""

    instances = []
    emit_frame_on_start = False

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.handlers = {}
        self.control = FakeCaptureControl()
        self.internal_control = FakeCaptureControl()
        self.instances.append(self)

    def event(self, handler):
        if handler.__name__ not in ("on_frame_arrived", "on_closed"):
            raise ValueError("Invalid Event Handler Use on_frame_arrived Or on_closed")
        self.handlers[handler.__name__] = handler
        return handler

    def start_free_threaded(self):
        if self.emit_frame_on_start:
            self.handlers["on_frame_arrived"](FakeWgcFrame(), self.internal_control)
        return self.control


class WindowsCaptureEventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.request = {"share_id": "share", "max_fps": 10,
                        "region": {"x": 0, "y": 0, "width": 20, "height": 10}}
        self.clock = FakeClock()
        self.source = FakeCaptureSession(self.request)
        self.session = FakeShare(self.request)
        self.task = asyncio.create_task(capture(self.session, self.request,
                                                lambda _request: self.source, self.clock))

    async def asyncTearDown(self):
        if not self.task.done():
            self.source.close_window()
            await self.task

    async def test_frames_flow_only_after_frame_arrived(self):
        self.assertEqual(self.session.frames, [])
        self.source.frame()
        await self.session.frame_event.wait()
        self.assertEqual(self.session.frames[0].size, (20, 10))

    async def test_no_events_capture_nothing(self):
        await checkpoint()
        self.assertEqual(self.session.frames, [])
        self.assertFalse(self.source.stopped)

    async def test_local_revoke_stops_the_capture_session(self):
        self.session.terminal.input.put_nowait("s")
        await self.task
        self.assertTrue(self.source.stopped)
        self.assertIsNone(self.session.share)

    async def test_window_close_revokes_and_stops_the_capture_session(self):
        self.source.close_window()
        await self.task
        self.assertTrue(self.source.stopped)
        self.assertIsNone(self.session.share)
        self.session.send.assert_awaited_once_with("share_stopped", share_id="share", reason="window closed")

    async def test_rate_cap_drops_frames_inside_the_event_handler(self):
        self.source.frame("red")
        await self.session.frame_event.wait()
        await checkpoint()
        self.session.frame_event = asyncio.Event()
        self.clock.now = 0.01
        self.source.frame("green")
        await checkpoint()
        self.assertEqual(len(self.session.frames), 1)
        await checkpoint()
        self.clock.now = 0.101
        self.source.frame("blue")
        await self.session.frame_event.wait()
        self.assertEqual(len(self.session.frames), 2)
        self.assertEqual(self.session.frames[-1].getpixel((0, 0)), (0, 0, 255))


class WindowsCaptureWindowSelectionTests(unittest.TestCase):
    def test_resolves_top_level_window_at_region_center(self):
        hwnd = 0x123456789
        user32 = type("User32", (), {})()
        user32.WindowFromPoint = Mock(return_value=hwnd)
        user32.GetAncestor = Mock(return_value=hwnd)
        user32.IsWindow = Mock(return_value=True)

        def get_rect(_hwnd, pointer):
            rectangle = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            rectangle.left, rectangle.top, rectangle.right, rectangle.bottom = -20, 10, 50, 80
            return True

        user32.GetWindowRect = Mock(side_effect=get_rect)
        region = {"x": 0, "y": 20, "width": 20, "height": 20}

        self.assertEqual(window_for_region(region, user32), (hwnd, (-20, 10)))
        user32.GetAncestor.assert_called_once_with(hwnd, 2)
        user32.WindowFromPoint.assert_called_once()


class WindowsCaptureBindingContractTests(unittest.TestCase):
    def setUp(self):
        StrictFakeWindowsCapture.instances.clear()
        StrictFakeWindowsCapture.emit_frame_on_start = False
        self.binding = SimpleNamespace(WindowsCapture=StrictFakeWindowsCapture)

    def test_window_adapter_registers_supported_events_and_converts_frames(self):
        request = {"region": {"x": 0, "y": 0, "width": 2, "height": 1}}
        with patch("partyline_helper.windows_capture.window_for_region", return_value=(123, (0, 0))), \
                patch.dict(sys.modules, {"windows_capture": self.binding}):
            source = _WindowsCapture(request)
            frames, closed = [], []
            source.start(lambda image, bounds: frames.append((image, bounds)),
                         lambda: closed.append(True))

        binding = StrictFakeWindowsCapture.instances[-1]
        self.assertEqual(binding.kwargs, {"window_hwnd": 123, "cursor_capture": True,
                                          "draw_border": False})
        self.assertEqual(set(binding.handlers), {"on_frame_arrived", "on_closed"})
        binding.handlers["on_frame_arrived"](FakeWgcFrame(), binding.internal_control)
        image, bounds = frames[0]
        self.assertEqual((image.size, image.getpixel((0, 0)), image.getpixel((1, 0))),
                         ((2, 1), (255, 0, 0), (0, 255, 0)))
        self.assertEqual(bounds, (0, 0))
        binding.handlers["on_closed"]()
        self.assertEqual(closed, [True])
        source.stop()
        self.assertEqual((binding.control.stop_count, binding.control.wait_count), (1, 1))

    def test_monitor_preview_uses_the_binding_one_based_indices(self):
        desktop = desktop_module.Desktop.__new__(desktop_module.Desktop)
        StrictFakeWindowsCapture.emit_frame_on_start = True
        with patch.object(desktop_module.Desktop, "supports_capture", new_callable=PropertyMock,
                          return_value=True), patch.dict(sys.modules, {"windows_capture": self.binding}):
            first = desktop.grab({"id": 1})
            second = desktop.grab({"id": 2})

        self.assertEqual([instance.kwargs["monitor_index"] for instance in
                          StrictFakeWindowsCapture.instances], [1, 2])
        self.assertEqual(first.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(second.getpixel((1, 0)), (0, 255, 0))


@unittest.skipUnless(__import__("sys").platform == "win32", "Windows Graphics Capture is Windows only")
class NativeWindowsCaptureTests(unittest.TestCase):
    def test_captures_a_real_tk_window(self):
        try:
            import windows_capture  # noqa: F401
        except (ImportError, OSError) as exc:
            self.skipTest(f"windows-capture binding is unavailable: {exc}")
        import tkinter as tk
        if sys.getwindowsversion().build < 18362:
            self.skipTest("HWND GraphicsCaptureItem requires Windows 10 build 18362 or newer")

        root = tk.Tk()
        root.title("Partyline WGC capture test")
        root.geometry("240x120+60+60")
        tk.Label(root, text="Windows Graphics Capture test").pack(expand=True)
        root.update()
        rectangle = {"x": root.winfo_rootx(), "y": root.winfo_rooty(),
                     "width": root.winfo_width(), "height": root.winfo_height()}
        request = {"region": rectangle, "max_fps": 10}
        source = None
        arrived, closed = Event(), Event()
        frames, errors = [], []

        def frame_arrived(image, _bounds):
            try:
                frames.append(image)
                root.after(0, root.quit)
            except Exception as exc:
                errors.append(exc)
            finally:
                arrived.set()

        try:
            source = _WindowsCapture(request)
            source.start(frame_arrived, closed.set)
            deadline_expired = []

            def timeout():
                deadline_expired.append(True)
                root.quit()

            # Failure bound only: a working capture quits on its first frame. A fresh hosted
            # runner can take over 750 ms to create the first D3D capture session.
            root.after(FIRST_FRAME_MS, timeout)
            root.mainloop()
            self.assertTrue(arrived.is_set(), f"no capture frame within {FIRST_FRAME_MS} ms")
            self.assertEqual(deadline_expired, [], "Windows Graphics Capture exceeded its frame deadline")
            self.assertEqual(errors, [])
            self.assertGreater(frames[0].width, 0)
            self.assertGreater(frames[0].height, 0)
        finally:
            if source is not None:
                stopping = Thread(target=source.stop, daemon=True)
                stopping.start()
                stopping.join(STOP_S)
                self.assertFalse(stopping.is_alive(),
                                 f"Windows Graphics Capture did not stop within {STOP_S} s")
            root.destroy()
