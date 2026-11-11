"""OS process-exit notifications for processes that are not our children."""

import asyncio
import os
import select
import sys
import threading


def wait_pid(pid, timeout=None):
    """True on exit, False at the one-shot deadline. No liveness scan loop."""
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # process already gone
                return True
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            milliseconds = 0xffffffff if timeout is None else int(timeout * 1000)
            result = kernel.WaitForSingleObject(handle, milliseconds)
            if result not in (0, 258):
                raise ctypes.WinError(ctypes.get_last_error())
            return result == 0
        finally:
            kernel.CloseHandle(handle)
    if hasattr(os, 'pidfd_open'):
        try:
            descriptor = os.pidfd_open(pid)
        except ProcessLookupError:
            return True
        try:
            return bool(select.select([descriptor], [], [], timeout)[0])
        finally:
            os.close(descriptor)
    with select.kqueue() as queue:  # macOS/BSD NOTE_EXIT
        event = select.kevent(pid, filter=select.KQ_FILTER_PROC,
                             flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                             fflags=select.KQ_NOTE_EXIT)
        try:
            return bool(queue.control([event], 1, timeout))
        except ProcessLookupError:
            return True


async def process_exited(pid):
    """Wait on a daemon thread; a cancelled observer cannot delay loop shutdown."""
    loop = asyncio.get_running_loop()
    result = loop.create_future()

    def complete(error):
        if not result.done():
            if error is None:
                result.set_result(None)
            else:
                result.set_exception(error)

    def wait():
        error = None
        try:
            wait_pid(pid)
        except Exception as exc:
            error = exc
        if not loop.is_closed():
            loop.call_soon_threadsafe(complete, error)

    threading.Thread(target=wait, name=f'process-exit-{pid}', daemon=True).start()
    await result
