"""Enumerate visible Windows top-level windows for local, explicit selection."""
import ctypes
import os
from ctypes import wintypes


def descendants(roots):  # pragma: no cover - Win32 process snapshot
    class ProcessEntry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", ctypes.c_long), ("flags", wintypes.DWORD),
                    ("exe", wintypes.WCHAR * 260)]
    kernel = ctypes.windll.kernel32
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        return None
    pairs, item = [], ProcessEntry()
    item.size = ctypes.sizeof(item)
    try:
        ok = kernel.Process32FirstW(handle, ctypes.byref(item))
        if not ok:
            return None
        while ok:
            pairs.append((item.pid, item.parent))
            ok = kernel.Process32NextW(handle, ctypes.byref(item))
    finally:
        kernel.CloseHandle(handle)
    result = set(roots)
    while True:
        updated = result | {pid for pid, parent in pairs if parent in result}
        if updated == result:
            return result
        result = updated


def windows(exclude=()):  # pragma: no cover - Win32 desktop APIs, covered by Windows CI
    user = ctypes.windll.user32
    kernel = ctypes.windll.kernel32
    user.OpenInputDesktop.restype = wintypes.HANDLE
    user.CloseDesktop.argtypes = [wintypes.HANDLE]
    user.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                               wintypes.DWORD, ctypes.c_void_p]
    desktop = user.OpenInputDesktop(0, False, 0x0001)
    if not desktop:
        return None
    try:
        name = ctypes.create_unicode_buffer(256)
        if not user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), None):
            return None
        if name.value.lower() != "default":
            return None
    finally:
        user.CloseDesktop(desktop)
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
    result = []
    excluded = descendants(set(exclude) | {os.getpid()})
    if excluded is None:
        return []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if not user.IsWindowVisible(hwnd):
            return True
        length = min(512, user.GetWindowTextLengthW(hwnd))
        if not length:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user.GetWindowTextW(hwnd, title, len(title))
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value or pid.value in excluded:
            return True
        process = kernel.OpenProcess(0x1000, False, pid.value)
        if not process:
            return True
        try:
            path = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(path))
            if not kernel.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
                return True
        finally:
            kernel.CloseHandle(process)
        exe = os.path.basename(path.value)
        if exe.lower() == "partylinehelper.exe":
            return True
        result.append({"hwnd": int(hwnd), "pid": pid.value, "title": title.value[:256], "process": exe[:128]})
        return True

    user.EnumWindows(visit, 0)
    return result
