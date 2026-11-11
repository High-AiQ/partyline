"""Windows low/high memory notifications, waited on by a cancellable thread."""

import asyncio
import ctypes
from ctypes import wintypes
import threading

LOW = 0
HIGH = 1
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF


class WindowsMemoryEvents:
    def __init__(self, loop, notify, kernel=None):
        self.loop, self.notify = loop, notify
        self.kernel = kernel or ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMemoryResourceNotification.argtypes = [ctypes.c_int]
        self.kernel.CreateMemoryResourceNotification.restype = wintypes.HANDLE
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        self.kernel.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
                                                       wintypes.BOOL, wintypes.DWORD]
        self.kernel.WaitForMultipleObjects.restype = wintypes.DWORD
        self.kernel.SetEvent.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handles = []
        try:
            for kind in (LOW, HIGH):
                handle = self.kernel.CreateMemoryResourceNotification(kind)
                if not handle:
                    raise OSError("CreateMemoryResourceNotification failed")
                self.handles.append(handle)
            stop = self.kernel.CreateEventW(None, True, False, None)
            if not stop:
                raise OSError("CreateEventW failed")
            self.handles.append(stop)
        except BaseException:
            for handle in self.handles:
                self.kernel.CloseHandle(handle)
            raise
        self.thread = threading.Thread(target=self._wait, name="memory-notification", daemon=True)
        self.thread.start()

    def _wait(self):
        kind = LOW
        while True:
            handles = (wintypes.HANDLE * 2)(self.handles[kind], self.handles[2])
            result = self.kernel.WaitForMultipleObjects(2, handles, False, INFINITE)
            if result != WAIT_OBJECT_0:
                return
            try:
                self.loop.call_soon_threadsafe(self.notify, None, kind == LOW)
            except RuntimeError:
                return
            # These handles are level-triggered. Wait for the opposite state
            # next, so a sustained low-memory signal cannot spin.
            kind = HIGH if kind == LOW else LOW

    async def close(self):
        self.kernel.SetEvent(self.handles[2])
        await asyncio.to_thread(self.thread.join)
        for handle in self.handles:
            self.kernel.CloseHandle(handle)
