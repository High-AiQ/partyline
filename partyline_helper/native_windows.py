"""Windows' native host stdio must preserve the binary length prefix."""
import ctypes
import os
import sys
from ctypes import wintypes


class ProcessEntry(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                ("parent", wintypes.DWORD), ("priority", ctypes.c_long), ("flags", wintypes.DWORD),
                ("exe", wintypes.WCHAR * 260)]


def binary_stdio():
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)


def chrome_parent(kernel=None, pid=None):
    """Find Chrome through the optional cmd.exe / Python launcher ancestors, fail closed."""
    kernel = kernel or ctypes.windll.kernel32
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle in (None, ctypes.c_void_p(-1).value):
        return 0
    rows, item = {}, ProcessEntry()
    item.size = ctypes.sizeof(item)
    try:
        available = kernel.Process32FirstW(handle, ctypes.byref(item))
        while available:
            rows[item.pid] = (item.parent, item.exe)
            available = kernel.Process32NextW(handle, ctypes.byref(item))
    finally:
        kernel.CloseHandle(handle)
    current = os.getpid() if pid is None else pid
    for _ in range(8):
        parent, _ = rows.get(current, (0, ""))
        if rows.get(parent, (0, ""))[1].lower() == "chrome.exe":
            return parent
        if not parent:
            return 0
        current = parent
    return 0
