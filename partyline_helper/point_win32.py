"""Win32 calls behind the cursor route of a point click. Windows only; tests use a fake of the same shape."""
import ctypes
import os
from ctypes import wintypes
from pathlib import PureWindowsPath

from .foreground_swap import activate
from .point_cursor import PointRefused
from .page_windows import RENDERER
from .uia_popups import WindowScope, configure, process_image
from .window_dpi import per_monitor

DOWN = {"left": 0x2, "right": 0x8}
UP = {"left": 0x4, "right": 0x10}
MOVE_TO = 0x8001 | 0x4000  # MOVE | ABSOLUTE | VIRTUALDESK: to a point of the whole desktop
WHEEL, HWHEEL, NOTCH = 0x800, 0x1000, 120  # vertical and horizontal wheel flags; one step of wheel
KEY_UP, UNICODE, EXTENDED = 0x2, 0x4, 0x1
STATE_KEYS = ((1, 0x10), (2, 0x11), (4, 0x12))  # VkKeyScanW's shift state bits: Shift, Ctrl, Alt
EXTENDED_KEYS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B}  # keys that need EXTENDED


class MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KeyInput(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class InputUnion(ctypes.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeyInput)]


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
        return self.user.WindowFromPoint(wintypes.POINT(x, y)) or 0

    def root(self, hwnd):
        return self.user.GetAncestor(hwnd, 2) if hwnd else 0  # GA_ROOT, the original safety boundary

    def describe(self, hwnd, granted):
        name = self.scope.window_class(hwnd) if hwnd else ""
        return {"hwnd": hwnd, "class": name, "granted_window": hwnd == granted,
                "page_area_child": bool(hwnd and self.user.GetAncestor(hwnd, 2) == granted
                                        and hwnd != granted and name == RENDERER)}

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

    def events(self, flags, spots=None, data=None):
        items = (Input * len(flags))()
        for index, (item, flag) in enumerate(zip(items, flags, strict=True)):
            item.type, item.union.mi.dwFlags = 0, flag  # INPUT_MOUSE
            if spots and spots[index]:
                item.union.mi.dx, item.union.mi.dy = spots[index]
            if data and data[index]:
                item.union.mi.mouseData = data[index] & 0xFFFFFFFF  # a negative step is a DWORD
        return items

    def dispatch(self, items):
        return self.user.SendInput(len(items), items, ctypes.sizeof(Input)), len(items)

    def desktop(self, x, y):
        """The point as 0..65535 across the virtual desktop, which SendInput's absolute moves use."""
        left, top, wide, high = (self.user.GetSystemMetrics(index) for index in (76, 77, 78, 79))
        # Windows maps the 16-bit value into half-open desktop pixels. Aim at the pixel centre.
        return ((2 * (x - left) + 1) * 65536 // (2 * wide),
                (2 * (y - top) + 1) * 65536 // (2 * high))

    def send(self, point, button, clicks):
        """Move to `point` and press and release, all in one call: the input lands on the point that was
        checked whatever the cursor did meanwhile, and nothing else's input can fall between the events."""
        flags = [MOVE_TO] + [DOWN[button], UP[button]] * clicks
        spots = [self.desktop(*point)] + [None] * (len(flags) - 1)
        return self.user.SendInput(len(flags), self.events(flags, spots), ctypes.sizeof(Input)), len(flags)

    def release(self, button):
        self.user.SendInput(1, self.events([UP[button]]), ctypes.sizeof(Input))

    def send_wheel(self, point, dx, dy):
        """Move to `point`, then turn the wheel: `dy` > 0 up and `dx` > 0 right, in whole steps."""
        flags, spots, data = [MOVE_TO], [self.desktop(*point)], [0]
        for flag, steps in ((WHEEL, dy), (HWHEEL, dx)):
            if steps:
                flags.append(flag), spots.append(None), data.append(steps * NOTCH)
        return self.dispatch(self.events(flags, spots, data))

    def send_drag(self, points):
        """Move to the first point, press, move through the others, release at the last: one call."""
        flags = [MOVE_TO, DOWN["left"]] + [MOVE_TO] * (len(points) - 1) + [UP["left"]]
        spots = [self.desktop(*points[0]), None] + [self.desktop(*p) for p in points[1:]] + [None]
        return self.dispatch(self.events(flags, spots))

    def keyboard(self, rows):
        """`rows`: (virtual key, scan code, flags) triples, sent in one call."""
        items = (Input * len(rows))()
        for item, (vk, scan, flags) in zip(items, rows, strict=True):
            item.type = 1  # INPUT_KEYBOARD
            item.union.ki.wVk, item.union.ki.wScan, item.union.ki.dwFlags = vk, scan, flags
        return self.dispatch(items)

    def send_text(self, text):
        """Type `text` as Unicode characters (a surrogate pair for one beyond the basic plane)."""
        rows = []
        for char in text.replace("\r\n", "\n"):
            if char in "\n\t":
                vk = 13 if char == "\n" else 9
                rows += [(vk, 0, 0), (vk, 0, KEY_UP)]
                continue
            units = char.encode("utf-16-le")
            for index in range(0, len(units), 2):
                unit = int.from_bytes(units[index:index + 2], "little")
                rows += [(0, unit, UNICODE), (0, unit, UNICODE | KEY_UP)]
        return self.keyboard(rows)

    def keystroke(self, modifiers, key, char=None):
        """`(modifier keys, virtual key)` to press; a character also takes the Shift, Ctrl and Alt that
        the keyboard layout needs to type it (a "?" is Shift+/ on some, a plain key on others)."""
        if key is not None:
            return list(modifiers), key
        scan = self.user.VkKeyScanW(ord(char)) & 0xFFFF
        if scan == 0xFFFF:
            raise PointRefused(f"{char!r} is not on the keyboard layout; nothing was sent. "
                               "Use screen_window_type")
        held = list(modifiers) + [vk for bit, vk in STATE_KEYS if scan >> 8 & bit and vk not in modifiers]
        return held, scan & 0xFF

    def send_keys(self, modifiers, key, char=None):
        """Hold the modifiers, press and release the key, release the modifiers: one call."""
        modifiers, vk = self.keystroke(modifiers, key, char)
        extra = EXTENDED if vk in EXTENDED_KEYS else 0
        rows = [(m, 0, EXTENDED if m in EXTENDED_KEYS else 0) for m in modifiers]
        rows += [(vk, 0, extra), (vk, 0, extra | KEY_UP)]
        rows += [(m, 0, KEY_UP | (EXTENDED if m in EXTENDED_KEYS else 0)) for m in reversed(modifiers)]
        return self.keyboard(rows)

    def release_keys(self, modifiers, key, char=None):
        """Lift the key and every modifier `send_keys` would hold, after a send that was cut short."""
        modifiers, vk = self.keystroke(modifiers, key, char)
        rows = [(m, 0, KEY_UP | (EXTENDED if m in EXTENDED_KEYS else 0)) for m in (vk, *reversed(modifiers))]
        self.keyboard(rows)

    def focused_password(self):
        """True: the focused field is a password; False: it is not; None: it cannot be told."""
        from .point_focus import focused_password
        return focused_password(self.user, self.scope)
