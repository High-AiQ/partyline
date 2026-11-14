"""Physical desktop coordinates and platform permission guards."""
import ctypes
from ctypes import wintypes
import os
import sys
import threading

def prepare():
    if sys.platform.startswith("linux") and (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
                                              or os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("Wayland is not supported yet "
                           "(needs the xdg-desktop-portal ScreenCast/RemoteDesktop route)")
    if sys.platform == "win32":
        # Must precede initializing the Windows Graphics Capture backend.
        if not ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            ctypes.windll.shcore.SetProcessDpiAwareness(2)


FRAME_SECONDS = 0.75
RELEASE_SECONDS = 2


def release(control, stop):
    """Stop a capture and wait for its thread, but never for long: a stuck one is abandoned.

    The wait runs in a daemon thread so a capture that never finishes cannot hold the caller or
    keep the helper from exiting. The thread is returned: if it is still alive the capture is
    still outstanding, and no further one may start until it ends.
    """
    def finish():
        if stop:
            control.stop()
        control.wait()

    worker = threading.Thread(target=finish, daemon=True)
    worker.start()
    worker.join(RELEASE_SECONDS)
    return worker


class Desktop:
    # Shared by every Desktop and so by every reconnected Session: one capture at a time, and none
    # while an abandoned one is still shutting down.
    _grab_lock = threading.Lock()
    _cleanup = None

    def __init__(self):
        prepare()
        from pynput.mouse import Controller
        self.scale = 1.0
        self.pointer_y_offset = 0
        if sys.platform == "darwin":
            from .retina import pointer_y_offset, scale_factor
            self.scale = scale_factor()
            self.pointer_y_offset = pointer_y_offset()
        try:
            self.mouse = Controller()
        except Exception as exc:
            raise RuntimeError("Unable to initialize pointer access") from exc

    @property
    def supports_capture(self):
        return sys.platform == "win32"

    def monitors(self):
        if not self.supports_capture:
            return []
        result = []
        monitors = []
        callback = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
        callback_type = callback(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.POINTER(wintypes.RECT), ctypes.c_long)

        def collect(handle, _dc, rectangle, _data):
            rect = rectangle.contents
            monitors.append((handle, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top))
            return 1

        ctypes.windll.user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
        for index, (handle, x, y, width, height) in enumerate(monitors, 1):
            dx, dy = ctypes.c_uint(), ctypes.c_uint()
            ctypes.windll.shcore.GetDpiForMonitor(handle, 0, ctypes.byref(dx), ctypes.byref(dy))
            result.append(dict(id=index, x=x, y=y, width=width, height=height,
                               scale=dx.value / 96 or 1.0, primary=x == 0 and y == 0))
        return result

    def grab(self, monitor):
        """Take an explicit monitor preview from its first Graphics Capture frame event."""
        if not self.supports_capture:
            raise RuntimeError("Monitor capture is unsupported on this platform")
        if not Desktop._grab_lock.acquire(blocking=False):
            raise RuntimeError("another monitor capture is still running")
        try:
            if Desktop._cleanup is not None and Desktop._cleanup.is_alive():
                raise RuntimeError("the previous monitor capture is still shutting down")
            Desktop._cleanup = None
            return self._capture(monitor)
        finally:
            Desktop._grab_lock.release()

    def _capture(self, monitor):
        from threading import Event
        from windows_capture import WindowsCapture
        from .capture_loop import _wgc_image

        arrived, frames, control = Event(), [], []
        capture = WindowsCapture(monitor_index=monitor["id"], cursor_capture=True, draw_border=False)

        @capture.event
        def on_frame_arrived(frame, capture_control):
            if not frames:
                frames.append(_wgc_image(frame))
                capture_control.stop()
                arrived.set()

        @capture.event
        def on_closed():
            arrived.set()

        control.append(capture.start_free_threaded())
        if not arrived.wait(FRAME_SECONDS) or not frames:
            Desktop._cleanup = release(control[0], stop=True)
            raise RuntimeError("Windows Graphics Capture did not deliver a monitor preview frame")
        Desktop._cleanup = release(control[0], stop=False)
        return frames[0]

    def pointer(self):
        x, y = self.mouse.position
        return round(x * self.scale), round((y + self.pointer_y_offset) * self.scale)

    def close(self):
        pass


class CursorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hCursor", wintypes.HANDLE), ("ptScreenPos", wintypes.POINT)]


def cursor_hidden():
    """Cheap Windows cursor visibility hint; failed queries leave capture unknown."""
    if sys.platform != "win32":
        return False
    info = CursorInfo()
    info.cbSize = ctypes.sizeof(info)
    return bool(ctypes.windll.user32.GetCursorInfo(ctypes.byref(info)) and not info.flags & 1)


def pointer_state(desktop, region):
    x, y = desktop.pointer()
    pointer = dict(x=x, y=y, visible=(region["x"] <= x < region["x"] + region["width"] and
                                    region["y"] <= y < region["y"] + region["height"]))
    if cursor_hidden():
        pointer["captured"] = True
    return pointer
