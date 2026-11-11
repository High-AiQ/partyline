"""Shallow overlapped directory reads; cancellation signals their native events."""

import asyncio
import ctypes
from ctypes import wintypes as w
import struct
import threading


class Overlapped(ctypes.Structure):
    _fields_ = [('internal', ctypes.c_size_t), ('internal_high', ctypes.c_size_t),
                ('offset', w.DWORD), ('offset_high', w.DWORD), ('event', w.HANDLE)]


def kernel_api():  # pragma: no cover - native Windows ABI declarations
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p,
                                w.DWORD, w.DWORD, w.HANDLE]
    api.CreateFileW.restype = w.HANDLE
    api.CreateEventW.argtypes = [ctypes.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR]
    api.CreateEventW.restype = w.HANDLE
    api.ReadDirectoryChangesW.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, w.BOOL,
        w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(Overlapped), ctypes.c_void_p]
    api.GetOverlappedResult.argtypes = [w.HANDLE, ctypes.POINTER(Overlapped),
                                       ctypes.POINTER(w.DWORD), w.BOOL]
    api.CancelIoEx.argtypes = [w.HANDLE, ctypes.POINTER(Overlapped)]
    api.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    api.ResetEvent.argtypes = [w.HANDLE]
    api.CloseHandle.argtypes = [w.HANDLE]
    return api


def paths_in(data, directory):
    paths, offset = set(), 0
    while offset < len(data):
        following, _action, length = struct.unpack_from('III', data, offset)
        paths.add(directory / data[offset + 12:offset + 12 + length].decode('utf-16-le'))
        if not following:
            break
        offset += following
    return paths


class DirectoryRead:
    def __init__(self, api, path, dispatch, failed):
        self.api, self.path, self.dispatch, self.failed = api, path, dispatch, failed
        self.guard = threading.Lock()
        self.closed = False
        self.handle = api.CreateFileW(str(path), 1, 7, None, 3, 0x42000000, None)
        if self.handle in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        self.overlap = Overlapped()
        self.overlap.event = api.CreateEventW(None, True, False, None)
        self.buffer = ctypes.create_string_buffer(65536)
        try:
            if not self.overlap.event:
                raise ctypes.WinError(ctypes.get_last_error())
            self.arm()  # Native observation starts before the caller scans.
        except BaseException:
            self.release()
            raise
        self.thread = threading.Thread(target=self.run, name='directory-events', daemon=True)
        try:
            self.thread.start()
        except BaseException:
            self.cancel()
            self.api.WaitForSingleObject(self.overlap.event, 0xffffffff)
            self.release()
            raise

    def arm(self):
        self.api.ResetEvent(self.overlap.event)
        if not self.api.ReadDirectoryChangesW(self.handle, self.buffer, len(self.buffer),
                False, 0x1 | 0x2 | 0x4 | 0x8 | 0x10 | 0x40, None,
                ctypes.byref(self.overlap), None):
            raise ctypes.WinError(ctypes.get_last_error())

    def run(self):
        try:
            while True:
                if self.api.WaitForSingleObject(self.overlap.event, 0xffffffff) != 0:
                    raise OSError('directory notification wait failed')
                with self.guard:
                    if self.closed:
                        return
                    count = w.DWORD()
                    if not self.api.GetOverlappedResult(self.handle, ctypes.byref(self.overlap),
                                                       ctypes.byref(count), False):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if not count.value:
                        raise OSError('directory notification buffer overflow; observation lost')
                    paths = paths_in(self.buffer.raw[:count.value], self.path)
                    self.arm()  # re-arm before handing the event to asyncio
                self.dispatch(paths)
        except Exception as exc:
            if not self.closed:
                if not self.path.is_dir():
                    self.dispatch({self.path})  # directory deletion re-arms its ancestor
                else:
                    self.failed(exc)

    def cancel(self):
        with self.guard:
            if self.closed:
                return
            self.closed = True
            self.api.CancelIoEx(self.handle, ctypes.byref(self.overlap))

    def release(self):
        self.api.CloseHandle(self.handle)
        if self.overlap.event:
            self.api.CloseHandle(self.overlap.event)

    async def close(self):
        self.cancel()
        await asyncio.to_thread(self.thread.join)
        self.release()


class WindowsNotify:
    directory_self_events = False  # ReadDirectoryChangesW omits changes to the watched directory itself.

    def __init__(self, loop, changed, failed, api=None):
        self.loop, self.changed, self.failed = loop, changed, failed
        self.api = api or kernel_api()
        self.watches, self.retired = {}, set()
        self.closed = False

    def dispatch(self, callback, value):
        if not self.closed:
            self.loop.call_soon_threadsafe(callback, value)

    def add(self, path):
        status = path.stat()
        identity = (status.st_dev, status.st_ino)
        if path in self.watches:
            if self.watches[path][1] == identity:
                return
            self.remove(path)
        watch = DirectoryRead(self.api, path, lambda paths: self.dispatch(self.changed, paths),
                              lambda error: self.dispatch(self.failed, error))
        self.watches[path] = (watch, identity)

    def remove(self, path):
        watch, _ = self.watches.pop(path)
        watch.cancel()
        retiring = asyncio.create_task(watch.close())
        self.retired.add(retiring)

        def finished(task):
            self.retired.discard(task)
            if not task.cancelled() and task.exception() is not None:
                self.dispatch(self.failed, task.exception())

        retiring.add_done_callback(finished)

    def retain(self, paths):
        for path in self.watches.keys() - paths:
            self.remove(path)

    async def close(self):
        self.closed = True
        for path in list(self.watches):
            self.remove(path)
        await asyncio.gather(*self.retired)
