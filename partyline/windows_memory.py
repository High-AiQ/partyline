"""Native Windows committed-memory limits for a process tree using a Job Object.

The capped test runner joins its own job before launching tests. Keep the handle
open until its children exit. Closing it does not kill the runner: Windows keeps
the job and its limits alive until the last associated process exits.
"""

import ctypes
import sys
from ctypes import wintypes


JOB_OBJECT_LIMIT_JOB_MEMORY = 0x200
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", BasicLimits),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _api():
    if sys.platform != "win32":
        raise OSError("Windows Job Objects require native Windows")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                      wintypes.DWORD], wintypes.BOOL),
        "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                        wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "IsProcessInJob": ([wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)],
                           wintypes.BOOL),
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result
    return api


def _check(result, operation):
    if not result:
        code = ctypes.get_last_error()
        raise OSError(code, f"{operation} failed: {ctypes.FormatError(code)}")
    return result


class WindowsJob:
    def __init__(self, limit: int, *, kill_on_close: bool = False, server: bool = False):
        if not 0 < limit <= ctypes.c_size_t(-1).value:
            raise ValueError("job memory limit must be positive and fit SIZE_T")
        self.api = _api()
        self.handle = _check(self.api.CreateJobObjectW(None, None), "CreateJobObjectW")
        self.limit = limit
        # The server's descendants enter separate verified jobs at suspended spawn.
        # They must not share the server's smaller memory budget.
        self.flags = (JOB_OBJECT_LIMIT_JOB_MEMORY | (0x2000 if kill_on_close else 0)
                      | (0x800 if server else 0))
        try:
            info = ExtendedLimits()
            info.BasicLimitInformation.LimitFlags = self.flags
            info.JobMemoryLimit = limit
            _check(self.api.SetInformationJobObject(
                self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info), ctypes.sizeof(info)), "SetInformationJobObject")
            self.verify_limit()
        except BaseException:
            self.close()
            raise

    def verify_limit(self) -> None:
        info = ExtendedLimits()
        _check(self.api.QueryInformationJobObject(
            self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info), ctypes.sizeof(info), None), "QueryInformationJobObject")
        if (info.BasicLimitInformation.LimitFlags & self.flags != self.flags
                or not 0 < info.JobMemoryLimit <= self.limit):
            raise OSError("Windows job memory limit is not enforced")

    def assign_current_process(self) -> None:
        self.assign_process(self.api.GetCurrentProcess())

    def assign_process(self, process) -> None:
        _check(self.api.AssignProcessToJobObject(self.handle, process), "AssignProcessToJobObject")
        member = wintypes.BOOL()
        _check(self.api.IsProcessInJob(process, self.handle, ctypes.byref(member)), "IsProcessInJob")
        if not member.value:
            raise OSError("process did not enter the Windows memory job")
        self.verify_limit()

    def terminate(self) -> None:
        _check(self.api.TerminateJobObject(self.handle, 1), "TerminateJobObject")

    def close(self) -> None:
        if self.handle is not None:
            handle, self.handle = self.handle, None
            _check(self.api.CloseHandle(handle), "CloseHandle")
