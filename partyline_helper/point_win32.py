"""Win32 calls behind the cursor route of a point click. Windows only; tests use a fake of the same shape."""
import ctypes
import os
from ctypes import wintypes
from pathlib import PureWindowsPath

from .foreground_swap import activate
from .uia_popups import WindowScope, configure, process_image
from .window_dpi import per_monitor

DOWN = {"left": 0x2, "right": 0x8}
UP = {"left": 0x4, "right": 0x10}


class MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class InputUnion(ctypes.Union):
    _fields_ = [("mi", MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", InputUnion)]


class Win32Pointer:  # pragma: no cover - Windows only
    def __init__(self, hwnd):
        self.user, self.kernel = ctypes.windll.user32, ctypes.windll.kernel32
        configure(self.user)
        self.user.GetForegroundWindow.restype = ctypes.c_void_p
        self.user.IsIconic.argtypes = [wintypes.HWND]
        self.user.WindowFromPoint.argtypes = [wintypes.POINT]
        self.user.WindowFromPoint.restype = wintypes.HWND
        self.user.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.user.SendInput.restype = wintypes.UINT
        self.scope = WindowScope(self.user, hwnd)

    def session(self):
        return per_monitor(self.user)

    def foreground(self):
        return self.user.GetForegroundWindow()

    def iconic(self, hwnd):
        return bool(self.user.IsIconic(hwnd))

    def owns(self, hwnd):
        return bool(hwnd) and self.scope.accepts(hwnd)

    def bring_forward(self, hwnd, current):
        return activate(self.user, lambda: self.kernel, hwnd, current)

    restore = bring_forward  # the same swap, the other way round

    def window_at(self, x, y):
        hit = self.user.WindowFromPoint(wintypes.POINT(x, y))
        return self.user.GetAncestor(hit, 2) if hit else 0  # GA_ROOT

    def image_name(self, hwnd):
        path = process_image(self.scope.process(hwnd))
        return PureWindowsPath(path).name.casefold() if path else ""

    def is_helper(self, hwnd):
        return self.scope.process(hwnd) == os.getpid()

    def cursor(self):
        point = wintypes.POINT()
        return (point.x, point.y) if self.user.GetCursorPos(ctypes.byref(point)) else None

    def move(self, x, y):
        return bool(self.user.SetCursorPos(int(x), int(y)))

    def events(self, flags):
        items = (Input * len(flags))()
        for item, flag in zip(items, flags, strict=True):
            item.type, item.union.mi.dwFlags = 0, flag  # INPUT_MOUSE, at the cursor's own position
        return items

    def send(self, button, clicks):
        """All presses and releases in one call, so nothing else's input can fall between them."""
        flags = [DOWN[button], UP[button]] * clicks
        return self.user.SendInput(len(flags), self.events(flags), ctypes.sizeof(Input)), len(flags)

    def release(self, button):
        self.user.SendInput(1, self.events([UP[button]]), ctypes.sizeof(Input))
