"""Native WinEvent notifications for window destruction and desktop switches.

The hook lives on a dedicated message-loop thread, as required for
WINEVENT_OUTOFCONTEXT. No HWND or desktop state is checked on a timer.
"""

import asyncio
import ctypes
from ctypes import wintypes as w
import sys
import threading

from partyline.file_events import Changes


class WindowEvents:
    def __init__(self, changes=None):
        self.changes = changes or Changes()
        self.thread = None

    async def __aenter__(self):
        if sys.platform != 'win32':
            return self
        self.loop = asyncio.get_running_loop()
        self.ready = self.loop.create_future()
        self.thread = threading.Thread(target=self._run, name='window-events', daemon=True)
        self.thread.start()
        try:
            await self.ready
        except BaseException:
            await self.__aexit__()
            raise
        return self

    def _started(self, error):
        if not self.ready.done():
            if error:
                self.ready.set_exception(error)
            else:
                self.ready.set_result(None)

    def _run(self):  # pragma: no cover - native Windows message loop
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(None, w.HANDLE, w.DWORD, w.HWND,
                                          w.LONG, w.LONG, w.DWORD, w.DWORD)
        self.user.SetWinEventHook.argtypes = [w.DWORD, w.DWORD, w.HMODULE, callback_type,
                                             w.DWORD, w.DWORD, w.DWORD]
        self.user.SetWinEventHook.restype = w.HANDLE
        self.user.UnhookWinEvent.argtypes = [w.HANDLE]
        self.user.PostThreadMessageW.argtypes = [w.DWORD, w.UINT, w.WPARAM, w.LPARAM]
        hooks = []

        def changed(hook, event, hwnd, object_id, child_id, thread, stamp):
            if event != 0x8001 or object_id == 0:  # only top-level window destruction
                self.loop.call_soon_threadsafe(self.changes.notify)

        callback = callback_type(changed)
        try:
            message = w.MSG()
            self.user.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            self.thread_id = kernel.GetCurrentThreadId()
            for event in (0x8001, 0x20, 0x3):  # destroy, desktop switch, foreground
                hook = self.user.SetWinEventHook(event, event, None, callback, 0, 0, 0)
                if not hook:
                    raise ctypes.WinError(ctypes.get_last_error())
                hooks.append(hook)
            self.loop.call_soon_threadsafe(self._started, None)
            while self.user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                self.user.TranslateMessage(ctypes.byref(message))
                self.user.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self.loop.call_soon_threadsafe(self._started, exc)
        finally:
            for hook in hooks:
                self.user.UnhookWinEvent(hook)

    async def wait(self):
        await self.changes.wait()

    async def __aexit__(self, *args):
        if self.thread is not None:
            if hasattr(self, 'thread_id'):
                self.user.PostThreadMessageW(self.thread_id, 0x12, 0, 0)  # WM_QUIT
            await asyncio.to_thread(self.thread.join)
