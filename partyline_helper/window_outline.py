"""Event-driven, capture-excluded outlines for individually granted windows."""
import asyncio
import ctypes
import sys
import threading
from ctypes import wintypes as w

from .border import MODE_COLORS, outside_strips
from .border_native import TkBackend

OUTLINE_COLOR = MODE_COLORS["window"]
OUTLINE_THICKNESS = 3
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_OBJECT_CLOAKED = 0x8017
EVENT_OBJECT_UNCLOAKED = 0x8018
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017
OBJID_WINDOW = 0


class WindowOutline:
    """Draw one HWND outline and update it only from its WinEvent notifications."""

    def __init__(self, hwnd, warning=None, backend_factory=None, user32=None, dwmapi=None, pid=None):
        self.hwnd, self.pid = hwnd, pid
        self.warning = warning or (lambda message: print(message, flush=True))
        self.backend_factory = backend_factory or (lambda error: TkBackend(error, windows=True))
        self.user32, self.dwmapi = user32, dwmapi
        self.backend = None
        self.failed = False
        self.hidden = False
        self.closed = False
        self.hook = None
        self.lock = threading.RLock()

    def _apis(self):
        if self.user32 is None:
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        if self.dwmapi is None:
            self.dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        return self.user32, self.dwmapi

    def frame_bounds(self):
        """Return DWM's physical-pixel frame bounds, which account for invisible resize borders."""
        user32, dwmapi = self._apis()
        user32.IsIconic.argtypes = [w.HWND]
        if user32.IsIconic(self.hwnd):
            return None
        rect = w.RECT()
        dwmapi.DwmGetWindowAttribute.argtypes = [w.HWND, w.DWORD, ctypes.c_void_p, w.DWORD]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
        result = dwmapi.DwmGetWindowAttribute(self.hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
        if result:
            raise OSError(result, "DWM could not read the shared window frame")
        cloaked = w.DWORD()
        cloak_result = dwmapi.DwmGetWindowAttribute(
            self.hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if not cloak_result and cloaked.value:
            return None
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top

    def update(self):
        with self.lock:
            if self.closed:
                return
            try:
                region = None if self.hidden else self.frame_bounds()
                if self.closed:
                    return
                if region is None:
                    if self.backend:
                        self.backend.hide()
                    return
                if self.backend is None:
                    backend = self.backend_factory(self._failed)
                    if self.closed:
                        backend.close()
                        return
                    self.backend = backend
                if self.closed:
                    return
                self.backend.show(outside_strips(
                    dict(zip(("x", "y", "width", "height"), region, strict=True)),
                    OUTLINE_THICKNESS), OUTLINE_COLOR)
            except Exception as exc:
                self._failed(exc)

    def _failed(self, error):
        with self.lock:
            if self.failed:
                return
            self.failed = True
            detail = " ".join(str(error).splitlines()) or error.__class__.__name__
            self.warning(f"Window outline unavailable; sharing continues: {detail}")

    def handle_event(self, event, hwnd, object_id=OBJID_WINDOW):
        """Apply one already-filtered test/native event without waiting for time."""
        with self.lock:
            if int(hwnd or 0) != int(self.hwnd) or object_id != OBJID_WINDOW or self.closed:
                return
            if event in (EVENT_SYSTEM_MINIMIZESTART, EVENT_OBJECT_CLOAKED):
                self.hidden = True
                if self.backend:
                    self.backend.hide()
            elif event in (EVENT_SYSTEM_MINIMIZEEND, EVENT_OBJECT_UNCLOAKED):
                self.hidden = False
                self.update()
            elif event == EVENT_OBJECT_LOCATIONCHANGE:
                self.update()
            elif event == EVENT_OBJECT_DESTROY:
                self.hidden = True
                if self.backend:
                    self.backend.hide()

    async def start(self):
        if sys.platform != "win32":
            return
        with self.lock:
            if self.closed:
                return
            self.hook = WindowOutlineEvents(self.hwnd, self.handle_event, self.warning, pid=self.pid)
            hook = self.hook
        await asyncio.to_thread(hook.start)
        await asyncio.to_thread(self.update)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            hook, backend = self.hook, self.backend
        if hook:
            hook.close()
        if backend:
            backend.close()


class WindowOutlineEvents:
    """One out-of-context WinEvent hook set for a single HWND."""

    EVENTS = (EVENT_OBJECT_LOCATIONCHANGE, EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND,
              EVENT_OBJECT_CLOAKED, EVENT_OBJECT_UNCLOAKED, EVENT_OBJECT_DESTROY)

    def __init__(self, hwnd, changed, warning, user32=None, pid=None):
        self.hwnd, self.changed, self.warning, self.pid, self.user32 = hwnd, changed, warning, pid, user32
        self.thread = None
        self.thread_id = None
        self.hooks = []
        self.closed = False
        import threading
        self.ready = threading.Event()

    def start(self):
        import threading
        self.thread = threading.Thread(target=self._run, name="window-outline-events", daemon=True)
        self.thread.start()
        self.ready.wait(3)

    def _run(self):  # pragma: no cover - exercised by native Windows integration
        user = self.user32 or ctypes.WinDLL("user32", use_last_error=True)
        self.user32 = user
        callback_type = ctypes.WINFUNCTYPE(None, w.HANDLE, w.DWORD, w.HWND,
                                           w.LONG, w.LONG, w.DWORD, w.DWORD)
        user.SetWinEventHook.argtypes = [w.DWORD, w.DWORD, w.HMODULE, callback_type,
                                         w.DWORD, w.DWORD, w.DWORD]
        user.SetWinEventHook.restype = w.HANDLE
        user.UnhookWinEvent.argtypes = [w.HANDLE]
        user.PostThreadMessageW.argtypes = [w.DWORD, w.UINT, w.WPARAM, w.LPARAM]
        def callback(hook, event, hwnd, object_id, child_id, thread_id, stamp):
            self.dispatch(event, hwnd, object_id, child_id)
        keepalive = callback_type(callback)
        try:
            message = w.MSG()
            user.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            for event in self.EVENTS:
                hook = user.SetWinEventHook(event, event, None, keepalive, self.pid or 0, 0, 0x0000)
                if not hook:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.hooks.append(hook)
            self.ready.set()
            while not self.closed and user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user.TranslateMessage(ctypes.byref(message))
                user.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self.warning(f"Window outline events unavailable; sharing continues: {exc}")
        finally:
            self.ready.set()
            for hook in self.hooks:
                user.UnhookWinEvent(hook)
            self.hooks.clear()

    def dispatch(self, event, hwnd, object_id, child_id):
        """Filter WinEvent's HWND, window object id, and non-child event target."""
        if (int(hwnd or 0) == int(self.hwnd) and object_id == OBJID_WINDOW and child_id == 0):
            self.changed(event, hwnd, object_id)

    def close(self):
        self.closed = True
        if self.thread_id and self.user32:
            self.user32.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
