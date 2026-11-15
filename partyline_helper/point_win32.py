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
MOVE_TO = 0x8001 | 0x4000  # MOVE | ABSOLUTE | VIRTUALDESK: to a point of the whole desktop


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

    def events(self, flags, spots=None):
        items = (Input * len(flags))()
        for index, (item, flag) in enumerate(zip(items, flags, strict=True)):
            item.type, item.union.mi.dwFlags = 0, flag  # INPUT_MOUSE
            if spots and spots[index]:
                item.union.mi.dx, item.union.mi.dy = spots[index]
        return items

    def desktop(self, x, y):
        """The point as 0..65535 across the virtual desktop, which SendInput's absolute moves use."""
        left, top, wide, high = (self.user.GetSystemMetrics(index) for index in (76, 77, 78, 79))
        return ((x - left) * 65535 // max(wide - 1, 1), (y - top) * 65535 // max(high - 1, 1))

    def send(self, point, button, clicks):
        """Move to `point` and press and release, all in one call: the input lands on the point that was
        checked whatever the cursor did meanwhile, and nothing else's input can fall between the events."""
        flags = [MOVE_TO] + [DOWN[button], UP[button]] * clicks
        spots = [self.desktop(*point)] + [None] * (len(flags) - 1)
        return self.user.SendInput(len(flags), self.events(flags, spots), ctypes.sizeof(Input)), len(flags)

    def release(self, button):
        self.user.SendInput(1, self.events([UP[button]]), ctypes.sizeof(Input))
