"""Capture only scoped HWNDs and compose their pixels into their desktop positions."""
import ctypes
from ctypes import wintypes

from PIL import Image

from .uia_popups import WindowScope, configure
from .window_grab import GrabError


def compose(windows):
    """Compose (rectangle, image) pairs without ever capturing desktop pixels.

    The image remembers the screen rectangle it covers (`info["rect"]`), so a click can be converted back.
    """
    left = min(rect[0] for rect, _ in windows)
    top = min(rect[1] for rect, _ in windows)
    right = max(rect[2] for rect, _ in windows)
    bottom = max(rect[3] for rect, _ in windows)
    if right <= left or bottom <= top or (right - left) * (bottom - top) > 100_000_000:
        raise GrabError("the shared window bounds are too large")
    image = Image.new("RGB", (right - left, bottom - top))
    for (x, y, _, _), part in windows:
        image.paste(part, (x - left, y - top))
    image.info["rect"] = (left, top, right, bottom)
    return image


def client_region(user, handle):  # pragma: no cover - native Windows APIs
    """The screen rectangle of a window's client area, or None when it has none."""
    rect, origin = wintypes.RECT(), wintypes.POINT(0, 0)
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    if (not user.GetClientRect(handle, ctypes.byref(rect))
            or not user.ClientToScreen(handle, ctypes.byref(origin))):
        return None
    if rect.right <= 0 or rect.bottom <= 0:
        return None
    return (origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom)


def grab_owned(hwnd, grab_one):  # pragma: no cover - native Windows APIs
    from .window_dpi import per_monitor
    user = ctypes.windll.user32
    with per_monitor(user):
        return _grab_owned(user, hwnd, grab_one)


def _grab_owned(user, hwnd, grab_one):  # pragma: no cover - native Windows APIs
    configure(user)
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    scope = WindowScope(user, hwnd)
    windows, names, regions = [], [], []
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
        if region := client_region(user, handle):
            regions.append(region)
    image = compose(windows)
    user.GetDpiForWindow.argtypes = [wintypes.HWND]
    user.GetDpiForWindow.restype = wintypes.UINT
    image.info.update(scoped_popups=names, regions=regions, dpi=int(user.GetDpiForWindow(hwnd) or 96))
    return image


def layout(hwnd):  # pragma: no cover - native Windows APIs
    """The union rectangle and client areas of the window and its owned popups, as a capture sees them."""
    from .window_dpi import per_monitor
    user = ctypes.windll.user32
    with per_monitor(user):
        configure(user)
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        scope = WindowScope(user, hwnd)
        rects, regions = [], []
        for handle in [hwnd, *reversed(scope.popups())]:
            rect = wintypes.RECT()
            if not user.GetWindowRect(handle, ctypes.byref(rect)):
                raise GrabError("a shared window is gone")
            rects.append((rect.left, rect.top, rect.right, rect.bottom))
            if region := client_region(user, handle):
                regions.append(region)
    return {"rect": (min(r[0] for r in rects), min(r[1] for r in rects),
                     max(r[2] for r in rects), max(r[3] for r in rects)), "regions": regions}
