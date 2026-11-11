"""Windows Graphics Capture HWND selection for a consented desktop rectangle."""

import ctypes
from ctypes import wintypes


def window_for_region(region, user32=None):
    """Resolve the top-level HWND beneath a region's centre and return its desktop bounds."""
    user32 = user32 or ctypes.windll.user32

    class Point(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    point = Point(region["x"] + region["width"] // 2, region["y"] + region["height"] // 2)
    user32.WindowFromPoint.argtypes = [Point]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    child = user32.WindowFromPoint(point)
    hwnd = user32.GetAncestor(child, 2) if child else None  # GA_ROOT
    if not hwnd or not user32.IsWindow(hwnd):
        raise RuntimeError("Could not resolve the shared region to a live window")
    rectangle = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
        raise RuntimeError("Could not read the shared window bounds")
    bounds = (rectangle.left, rectangle.top, rectangle.right, rectangle.bottom)
    if not (bounds[0] <= point.x < bounds[2] and bounds[1] <= point.y < bounds[3]):
        raise RuntimeError("The shared region does not belong to a capturable window")
    return int(hwnd), bounds[:2]
