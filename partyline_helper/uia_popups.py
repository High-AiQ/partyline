"""Win32 ownership boundary for a grant and its visible, same-process popups."""
import ctypes
from ctypes import wintypes as w


class WindowScope:
    def __init__(self, user, hwnd, enumerate_windows=None):
        self.user, self.hwnd = user, hwnd
        self.enumerate_windows = enumerate_windows or self.windows
        self.pid = self.process(hwnd)

    def process(self, hwnd):
        pid = w.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def owns(self, hwnd):
        """Every link must belong to the granted process; cycles and missing owners fail closed."""
        seen = set()
        while hwnd and hwnd not in seen:
            if not self.pid or self.process(hwnd) != self.pid:
                return False
            if hwnd == self.hwnd:
                return True
            seen.add(hwnd)
            hwnd = self.user.GetWindow(hwnd, 4)  # GW_OWNER, not another browser window's root
        return False

    def accepts(self, hwnd):
        top = self.user.GetAncestor(hwnd, 2)  # GA_ROOT (does not follow owners)
        return bool(top and self.pid and self.process(hwnd) == self.pid and self.owns(top) and
                    (top == self.hwnd or self.user.IsWindowVisible(top)))

    def popups(self):
        return [hwnd for hwnd in self.enumerate_windows()
                if hwnd != self.hwnd and self.user.IsWindowVisible(hwnd) and self.owns(hwnd)]

    def windows(self):  # pragma: no cover - Win32 enumeration callback ABI
        found = []
        def visit(hwnd, _):
            found.append(hwnd)
            return True
        callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)(visit)
        self.user.EnumWindows(callback, 0)
        return found


def configure(user):  # pragma: no cover - Windows ABI
    user.GetWindow.argtypes = [w.HWND, w.UINT]
    user.GetWindow.restype = w.HWND
    user.GetAncestor.argtypes = [w.HWND, w.UINT]
    user.GetAncestor.restype = w.HWND
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user.IsWindowVisible.argtypes = [w.HWND]
    user.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM), w.LPARAM]


class PopupEvents:
    """Route lifecycle events even when a disappearing popup no longer has an owner."""
    def __init__(self, scope, changed):
        self.scope, self.changed = scope, changed
        self.known = set(scope.popups())

    def event(self, hwnd, object_id):
        if not hwnd or object_id != 0:  # OBJID_WINDOW only
            return
        if hwnd in self.known or self.scope.owns(hwnd):
            if self.scope.accepts(hwnd):
                self.known.add(hwnd)
            else:
                self.known.discard(hwnd)
            self.changed()


def sender_in_scope(provider, sender):
    """UIA events may originate on a handleless option; resolve its nearest HWND."""
    same_process = True
    try:
        for _ in range(100):
            if sender is None:
                return False
            same_process &= provider.prop(sender, "ProcessId") == provider.scope.pid
            handle = provider.prop(sender, "NativeWindowHandle")
            if handle:
                if provider.user32.GetAncestor(handle, 2) == provider.hwnd:
                    return True  # hosted content is part of the explicitly granted subtree
                return same_process and provider.scope.accepts(handle)
            sender = provider.walker.GetParentElement(sender)
    except Exception:  # stale/destroyed UIA sender; WinEvents cover popup disappearance
        return False
    return False


def hook_popups(user, scope, changed, refresh=lambda: None):  # pragma: no cover - native WinEvent ABI
    callback_type = ctypes.WINFUNCTYPE(None, w.HANDLE, w.DWORD, w.HWND,
                                      w.LONG, w.LONG, w.DWORD, w.DWORD)
    user.SetWinEventHook.argtypes = [w.DWORD, w.DWORD, w.HMODULE, callback_type,
                                    w.DWORD, w.DWORD, w.DWORD]
    user.SetWinEventHook.restype = w.HANDLE
    user.UnhookWinEvent.argtypes = [w.HANDLE]
    def notify():
        changed()
        refresh()  # posts a message; never register COM handlers inside the WinEvent callback
    events = PopupEvents(scope, notify)
    callback = callback_type(lambda hook, event, hwnd, obj, child, thread, stamp:
                             events.event(hwnd, obj))
    # Destroy/show/hide. Register before the initial snapshot; no timed discovery loop.
    hook = user.SetWinEventHook(0x8001, 0x8003, None, callback, scope.pid, 0, 0)
    if not hook:
        raise ctypes.WinError(ctypes.get_last_error())
    return hook, callback
