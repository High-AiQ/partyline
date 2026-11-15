"""Pixels of one granted window: its own content, never the desktop beneath or around it.

Windows Graphics Capture takes a single HWND, so a covered or partly off-screen window still comes out whole;
`PrintWindow(PW_RENDERFULLCONTENT)` is the fallback for a window it cannot take. Neither restores or raises a
window: a minimised one is refused. Protected (DRM) content is drawn black by Windows itself.
"""
import sys
import threading

WGC_SECONDS = 3  # how long one frame may take to arrive from Graphics Capture


class GrabError(Exception):
    """The window cannot be captured; the message is for the agent."""


class WindowGrab:
    """The Windows capture backend; tests replace it with a fake that has the same two methods."""

    def minimized(self, hwnd):
        if sys.platform != "win32":
            raise GrabError("window screenshots need Windows")
        return self.iconic(hwnd)

    def grab(self, hwnd):
        """One RGB image of the window, from Graphics Capture or else PrintWindow."""
        if sys.platform != "win32":
            raise GrabError("window screenshots need Windows")
        from .window_grab_owned import grab_owned
        return grab_owned(hwnd, self.grab_one)

    def grab_one(self, hwnd):
        try:
            return self.wgc(hwnd)
        except Exception:  # noqa: BLE001 - any Graphics Capture failure falls back to PrintWindow
            return self.print_window(hwnd)

    @staticmethod
    def iconic(hwnd):  # pragma: no cover - Windows only
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        return bool(user32.IsIconic(hwnd))

    @staticmethod
    def wgc(hwnd):  # pragma: no cover - Windows Graphics Capture
        from windows_capture import WindowsCapture
        from .capture_loop import _wgc_image

        arrived, box = threading.Event(), []
        capture = WindowsCapture(window_hwnd=hwnd, cursor_capture=False, draw_border=False)

        @capture.event
        def on_frame_arrived(frame, _control):
            if not box:
                box.append(_wgc_image(frame))
                arrived.set()

        @capture.event
        def on_closed():
            arrived.set()

        control = capture.start_free_threaded()
        try:
            arrived.wait(WGC_SECONDS)
        finally:
            control.stop()
            control.wait()
        if not box:
            raise GrabError("Graphics Capture produced no frame")
        return box[0]

    @staticmethod
    def print_window(hwnd):  # pragma: no cover - GDI PrintWindow
        import ctypes
        from ctypes import wintypes
        from PIL import Image

        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        handle = ctypes.c_void_p
        for name, args, result in (
                ("GetWindowDC", [wintypes.HWND], handle),
                ("ReleaseDC", [wintypes.HWND, handle], ctypes.c_int),
                ("PrintWindow", [wintypes.HWND, handle, wintypes.UINT], wintypes.BOOL),
                ("GetWindowRect", [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL)):
            function = getattr(user32, name)
            function.argtypes, function.restype = args, result
        for name, args, result in (
                ("CreateCompatibleDC", [handle], handle), ("CreateCompatibleBitmap", [handle, ctypes.c_int,
                                                                                      ctypes.c_int], handle),
                ("SelectObject", [handle, handle], handle), ("DeleteObject", [handle], wintypes.BOOL),
                ("DeleteDC", [handle], wintypes.BOOL),
                ("GetDIBits", [handle, handle, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                               ctypes.c_void_p, wintypes.UINT], ctypes.c_int)):
            function = getattr(gdi32, name)
            function.argtypes, function.restype = args, result

        class Header(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG), ("height", wintypes.LONG),
                        ("planes", wintypes.WORD), ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                        ("image", wintypes.DWORD), ("x", wintypes.LONG), ("y", wintypes.LONG),
                        ("used", wintypes.DWORD), ("important", wintypes.DWORD)]

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise GrabError("the window is gone")
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 0 or height <= 0:
            raise GrabError("the window has no visible area")
        source = user32.GetWindowDC(hwnd)
        memory, bitmap = gdi32.CreateCompatibleDC(source), gdi32.CreateCompatibleBitmap(source, width, height)
        try:
            previous = gdi32.SelectObject(memory, bitmap)
            if not user32.PrintWindow(hwnd, memory, 2):  # PW_RENDERFULLCONTENT
                raise GrabError("the window did not draw itself when asked")
            header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
            buffer = ctypes.create_string_buffer(width * height * 4)
            gdi32.SelectObject(memory, previous)
            if gdi32.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(header), 0) != height:
                raise GrabError("the window's pixels could not be read")
            return Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB")
        finally:
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory)
            user32.ReleaseDC(hwnd, source)
