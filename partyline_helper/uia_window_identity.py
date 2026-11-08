"""Attach a unique lifetime marker to the selected HWND, so recycled handles cannot inherit consent."""
import ctypes
import sys
import uuid


def mark(hwnd):  # pragma: no cover - Windows window properties
    if sys.platform != "win32":
        return None
    user = ctypes.windll.user32
    user.SetPropW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p]
    user.SetPropW.restype = ctypes.c_int
    name = "Partyline.WindowConsent." + uuid.uuid4().hex
    return name if user.SetPropW(hwnd, name, 1) else None


def live(grant):  # pragma: no cover - Windows window properties
    marker = grant.get("marker")
    if not marker:
        return False
    user = ctypes.windll.user32
    user.GetPropW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    user.GetPropW.restype = ctypes.c_void_p
    return user.GetPropW(grant["hwnd"], marker) == 1


def unmark(grant):  # pragma: no cover - Windows window properties
    marker = grant.get("marker")
    if marker:
        user = ctypes.windll.user32
        user.RemovePropW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        user.RemovePropW(grant["hwnd"], marker)
