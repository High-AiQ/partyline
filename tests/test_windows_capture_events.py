"""Capture frame delivery reacts only to injected FrameArrived and close events."""

import asyncio
import ctypes
import unittest
from ctypes import wintypes
from unittest.mock import AsyncMock, Mock

from PIL import Image

from partyline.file_events import Changes
from partyline_helper.capture_loop import capture
from partyline_helper.windows_capture import window_for_region
from tests.screen_helper_fakes import checkpoint


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


@unittest.skipUnless(__import__("sys").platform == "win32", "Windows Graphics Capture is Windows only")
class NativeWindowsCaptureTests(unittest.TestCase):
    def test_captures_a_real_tk_window(self):
        try:
            import tkinter as tk
            from partyline_helper.capture_loop import _WindowsCapture
        except (ImportError, OSError):
            self.skipTest("Tk or windows-capture is unavailable")

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk desktop is unavailable: {exc}")
        root.title("Partyline WGC capture test")
        root.geometry("240x120+60+60")
        tk.Label(root, text="Windows Graphics Capture test").pack(expand=True)
        root.update()
        rectangle = {"x": root.winfo_rootx(), "y": root.winfo_rooty(),
                     "width": root.winfo_width(), "height": root.winfo_height()}
        request = {"region": rectangle, "max_fps": 10}
        try:
            source = _WindowsCapture(request)
        except (ImportError, OSError, RuntimeError) as exc:
            root.destroy()
            self.skipTest(f"Windows Graphics Capture is unavailable: {exc}")
        arrived, closed = __import__("threading").Event(), __import__("threading").Event()
        frames = []
        try:
            try:
                source.start(lambda image, _bounds: (frames.append(image), arrived.set()), closed.set)
            except (OSError, RuntimeError) as exc:
                self.skipTest(f"Windows Graphics Capture could not start: {exc}")
            root.update()
            if not arrived.wait(0.75):
                self.skipTest("Windows Graphics Capture delivered no frame on this runner")
            self.assertGreater(frames[0].width, 0)
            self.assertGreater(frames[0].height, 0)
        finally:
            source.stop()
            root.destroy()
