"""Foreground Windows startup with a verified server memory cap."""

import ctypes as c
from ctypes import wintypes as w

from .windows_memory import WindowsJob

_server_job = None


def breakaway_flags():
    """Only explicitly managed attachments leave the server's smaller job."""
    return 0x1000000 if _server_job is not None else 0


class MemoryStatus(c.Structure):
    _fields_ = [('length', w.DWORD), ('load', w.DWORD)] + [
        (name, c.c_ulonglong) for name in
        ('total', 'available', 'page_total', 'page_available', 'virtual', 'virtual_available', 'extended')
    ]


def host_memory_bytes():
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.GlobalMemoryStatusEx.argtypes = [c.POINTER(MemoryStatus)]
    kernel.GlobalMemoryStatusEx.restype = w.BOOL
    info = MemoryStatus()
    info.length = c.sizeof(info)
    if not kernel.GlobalMemoryStatusEx(c.byref(info)):
        raise c.WinError(c.get_last_error())
    return info.total


def serve(arguments, main):
    from .bind import load_dotenv
    from .server_memory import limit_bytes

    global _server_job
    load_dotenv()
    job = WindowsJob(limit_bytes(), server=True)
    try:
        job.assign_current_process()
        _server_job = job
        return main(arguments)
    finally:
        _server_job = None
        job.close()
