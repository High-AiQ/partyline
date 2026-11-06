"""Physical desktop coordinates and platform permission guards."""
import ctypes
import os
import sys

from PIL import Image

SCREEN_PERMISSION = ("macOS: Open System Settings > Privacy & Security > Screen Recording "
                     "(Screen & System Audio Recording on newer macOS), enable your terminal or Python, "
                     "then quit and reopen it.")


def prepare():
    if sys.platform.startswith("linux") and (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
                                              or os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("Wayland is not supported yet "
                           "(needs the xdg-desktop-portal ScreenCast/RemoteDesktop route)")
    if sys.platform == "win32":
        # Must precede importing pynput or initializing mss.
        if not ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            ctypes.windll.shcore.SetProcessDpiAwareness(2)


class Desktop:
    def __init__(self):
        prepare()
        if sys.platform == "darwin":
            core = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
            core.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
            if not core.CGPreflightScreenCaptureAccess():
                raise RuntimeError(SCREEN_PERMISSION)
        import mss
        from pynput.mouse import Controller
        self.scale = 1.0
        self.pointer_y_offset = 0
        if sys.platform == "darwin":
            from .retina import pointer_y_offset, scale_factor
            self.scale = scale_factor()
            self.pointer_y_offset = pointer_y_offset()
        try:
            self.capture = mss.mss()
            try:
                self.mouse = Controller()
            except Exception:
                self.capture.close()
                raise
        except Exception as exc:
            raise RuntimeError("Unable to initialize desktop capture/pointer; "
                               "check display permissions") from exc

    def monitors(self):
        result = []
        for index, monitor in enumerate(self.capture.monitors[1:], 1):
            x, y = monitor["left"], monitor["top"]
            scale = self.scale
            if sys.platform == "win32":
                # MonitorFromPoint packs a signed POINT into the by-value argument.
                point = ctypes.c_longlong(((y & 0xffffffff) << 32) | (x & 0xffffffff))
                function = ctypes.windll.user32.MonitorFromPoint
                function.restype = ctypes.c_void_p
                handle = ctypes.c_void_p(function(point, 2))
                dx, dy = ctypes.c_uint(), ctypes.c_uint()
                ctypes.windll.shcore.GetDpiForMonitor(handle, 0, ctypes.byref(dx), ctypes.byref(dy))
                scale = dx.value / 96 or 1.0
            factor = self.scale
            result.append(dict(id=index, x=round(x * factor), y=round(y * factor),
                               width=round(monitor["width"] * factor),
                               height=round(monitor["height"] * factor),
                               scale=scale, primary=x == 0 and y == 0))
        return result

    def grab(self, region):
        factor = self.scale
        coordinates = {key: value / factor if factor != 1 else value for key, value in region.items()
                       if key in ("x", "y", "width", "height")}
        try:
            shot = self.capture.grab(dict(left=coordinates["x"], top=coordinates["y"],
                                          width=coordinates["width"], height=coordinates["height"]))
        except Exception as exc:
            hint = " " + SCREEN_PERMISSION if sys.platform == "darwin" else " Check display access."
            raise RuntimeError("Desktop capture failed." + hint) from exc
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        if sys.platform == "darwin" and image.getextrema() == ((0, 0), (0, 0), (0, 0)):
            raise RuntimeError("Blank capture. " + SCREEN_PERMISSION)
        return image

    def pointer(self):
        x, y = self.mouse.position
        return round(x * self.scale), round((y + self.pointer_y_offset) * self.scale)

    def close(self):
        self.capture.close()
