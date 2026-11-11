"""Process-shared ownership locks for Unix and native Windows."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
import errno
import os
import sys
import threading


def try_lock(descriptor: int) -> None:
    """Acquire without waiting; normalize only contention to BlockingIOError."""
    if sys.platform == "win32":
        import msvcrt

        # Lock one reserved byte, including on an empty file. Every descriptor
        # must use the same offset; msvcrt locks from its current file position.
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno == errno.EACCES:
                raise BlockingIOError(errno.EAGAIN, "runtime lock is held") from exc
            raise
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def lock(descriptor: int) -> None:
    """Let the OS block on ownership release, without a retry timer."""
    if sys.platform == "win32":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        class Overlapped(ctypes.Structure):
            _fields_ = [("internal", ctypes.c_size_t), ("internal_high", ctypes.c_size_t),
                        ("offset", wintypes.DWORD), ("offset_high", wintypes.DWORD),
                        ("event", wintypes.HANDLE)]

        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
        overlap = Overlapped()
        if not api.LockFileEx(msvcrt.get_osfhandle(descriptor), 2, 0, 1, 0, ctypes.byref(overlap)):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        import fcntl
        fcntl.flock(descriptor, fcntl.LOCK_EX)


def unlock(descriptor: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def _descriptor(path):
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def exclusive(path):
    with _descriptor(path) as descriptor:
        lock(descriptor)
        try:
            yield
        finally:
            unlock(descriptor)


@asynccontextmanager
async def exclusive_async(path):
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try_lock(descriptor)
    except BlockingIOError:
        pass  # The OS waiter below takes over only for real contention.
    except BaseException:
        os.close(descriptor)
        raise
    else:
        try:
            yield
        finally:
            unlock(descriptor)
            os.close(descriptor)
        return
    loop = asyncio.get_running_loop()
    result = loop.create_future()

    guard = threading.Lock()
    state = {'ready': False, 'cancelled': False, 'closed': False, 'error': None}

    def cleanup():
        if not state['closed']:
            if state['error'] is None:
                unlock(descriptor)
            os.close(descriptor)
            state['closed'] = True

    def acquired():
        with guard:
            if state['cancelled']:
                cleanup()
            elif state['error'] is not None:
                cleanup()
                result.set_exception(state['error'])
            else:
                result.set_result(None)

    def acquire():
        error = None
        try:
            lock(descriptor)
        except BaseException as exc:
            error = exc
        with guard:
            state.update(ready=True, error=error)
            if state['cancelled']:
                cleanup()
                return
        try:
            loop.call_soon_threadsafe(acquired)
        except RuntimeError:
            with guard:
                cleanup()

    threading.Thread(target=acquire, name='runtime-lock', daemon=True).start()
    try:
        await result
    except asyncio.CancelledError:
        # Cleanup belongs to the worker until its native wait finishes. A queued
        # loop callback may never run after shutdown, so cancellation also cleans
        # an already-acquired descriptor here, exactly once under the guard.
        with guard:
            state['cancelled'] = True
            if state['ready']:
                cleanup()
        raise
    try:
        yield
    finally:
        with guard:
            cleanup()
