"""Where a Chrome window's page is on screen, read from Windows: renderer child windows, UIA documents, DPI.

Every rectangle is in physical screen pixels (this thread is made per-monitor aware around each call)."""
import ctypes
from ctypes import wintypes

RENDERER = "Chrome_RenderWidgetHostHWND"
CONTROL_TYPE, DOCUMENT, DESCENDANTS, OFFSCREEN = 30003, 50030, 4, 30022  # UIA property ids and scope


def user32():  # pragma: no cover - Windows only
    user = ctypes.windll.user32
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetDpiForWindow.argtypes = [wintypes.HWND]
    user.GetDpiForWindow.restype = wintypes.UINT
    return user


def renderers(hwnd):  # pragma: no cover - Windows only
    """The screen rectangles of the visible legacy renderer child windows of this top-level window."""
    from .window_dpi import per_monitor
    user, found = user32(), []
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumChildWindows.argtypes = [wintypes.HWND, callback, wintypes.LPARAM]

    def visit(child, _):
        name = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(child, name, len(name))
        if name.value == RENDERER and user.IsWindowVisible(child) and user.GetAncestor(child, 2) == hwnd:
            rect = wintypes.RECT()
            if user.GetWindowRect(child, ctypes.byref(rect)):
                found.append((rect.left, rect.top, rect.right, rect.bottom))
        return True

    with per_monitor(user):
        user.EnumChildWindows(hwnd, callback(visit), 0)
    return found


def read_documents(hwnd):  # pragma: no cover - Windows only
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as uia
    automation = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)
    condition = automation.CreatePropertyCondition(CONTROL_TYPE, DOCUMENT)
    nodes = automation.ElementFromHandle(hwnd).FindAll(DESCENDANTS, condition)
    found = []
    for index in range(nodes.Length):
        node = nodes.GetElement(index)
        rect = node.CurrentBoundingRectangle
        if not node.GetCurrentPropertyValue(OFFSCREEN):
            found.append((rect.left, rect.top, rect.right, rect.bottom))
    return found


def documents(hwnd):  # pragma: no cover - Windows only
    """The screen rectangles of the UIA Document elements inside the window (the active tab's page)."""
    import comtypes
    from .window_dpi import per_monitor
    comtypes.CoInitialize()
    try:
        with per_monitor(user32()):
            return read_documents(hwnd)
    except (OSError, comtypes.COMError):
        return []
    finally:
        comtypes.CoUninitialize()


def scale(hwnd):  # pragma: no cover - Windows only
    """Screen pixels per device-independent pixel on the window's monitor."""
    return user32().GetDpiForWindow(hwnd) / 96


class PageSources:
    """The three places the page's rectangle can come from; tests replace them with fakes."""

    def __init__(self, renderers=renderers, documents=documents, scale=scale):
        self.renderers, self.documents, self.scale = renderers, documents, scale
