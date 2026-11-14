"""Capture only scoped HWNDs and compose their pixels into their desktop positions."""
import ctypes
from ctypes import wintypes

from PIL import Image

from .uia_popups import WindowScope, configure
from .window_grab import GrabError


def compose(windows):
    """Compose (rectangle, image) pairs without ever capturing desktop pixels."""
    left = min(rect[0] for rect, _ in windows)
    top = min(rect[1] for rect, _ in windows)
    right = max(rect[2] for rect, _ in windows)
    bottom = max(rect[3] for rect, _ in windows)
    if right <= left or bottom <= top or (right - left) * (bottom - top) > 100_000_000:
        raise GrabError("the shared window bounds are too large")
    image = Image.new("RGB", (right - left, bottom - top))
    for (x, y, _, _), part in windows:
        image.paste(part, (x - left, y - top))
    return image


def grab_owned(hwnd, grab_one):  # pragma: no cover - native Windows APIs
    user = ctypes.windll.user32
    configure(user)
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    scope = WindowScope(user, hwnd)
    windows, names = [], []
    # EnumWindows is front-to-back; paint the furthest popup first.
    for handle in [hwnd, *reversed(scope.popups())]:
        if handle != hwnd and not scope.accepts(handle):
            raise GrabError("an owned window changed during capture")
        rect = wintypes.RECT()
        if not user.GetWindowRect(handle, ctypes.byref(rect)):
            raise GrabError("a shared window is gone")
        pixels = grab_one(handle)
        if handle != hwnd and not scope.accepts(handle):
            raise GrabError("an owned window changed during capture")
        if handle != hwnd:
            title = ctypes.create_unicode_buffer(121)
            user.GetWindowTextW(handle, title, len(title))
            names.append(title.value or "owned popup")
        windows.append(((rect.left, rect.top, rect.right, rect.bottom), pixels))
    image = compose(windows)
    image.info["scoped_popups"] = names
    return image
