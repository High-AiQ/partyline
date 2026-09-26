"""ctypes declarations for native ConPTY sessions (Windows 10 1809+)."""

import ctypes as c
from ctypes import wintypes as w
import sys


class Coord(c.Structure):
    _fields_ = [('X', c.c_short), ('Y', c.c_short)]


class Startup(c.Structure):
    _fields_ = [
        ('cb', w.DWORD), ('lpReserved', w.LPWSTR), ('lpDesktop', w.LPWSTR),
        ('lpTitle', w.LPWSTR), ('dwX', w.DWORD), ('dwY', w.DWORD),
        ('dwXSize', w.DWORD), ('dwYSize', w.DWORD), ('dwXCountChars', w.DWORD),
        ('dwYCountChars', w.DWORD), ('dwFillAttribute', w.DWORD), ('dwFlags', w.DWORD),
        ('wShowWindow', w.WORD), ('cbReserved2', w.WORD), ('lpReserved2', c.c_void_p),
        ('hStdInput', w.HANDLE), ('hStdOutput', w.HANDLE), ('hStdError', w.HANDLE),
    ]


class StartupEx(c.Structure):
    _fields_ = [('StartupInfo', Startup), ('lpAttributeList', c.c_void_p)]


class ProcessInfo(c.Structure):
    _fields_ = [('hProcess', w.HANDLE), ('hThread', w.HANDLE),
                ('dwProcessId', w.DWORD), ('dwThreadId', w.DWORD)]


def api():
    if sys.platform != 'win32':
        raise OSError('ConPTY requires native Windows')
    kernel = c.WinDLL('kernel32', use_last_error=True)
    ptr, handle = c.c_void_p, w.HANDLE
    signatures = {
        'CreatePipe': ([c.POINTER(handle), c.POINTER(handle), ptr, w.DWORD], w.BOOL),
        'CreatePseudoConsole': ([Coord, handle, handle, w.DWORD, c.POINTER(handle)], w.LONG),
        'ResizePseudoConsole': ([handle, Coord], w.LONG),
        'ClosePseudoConsole': ([handle], None),
        'InitializeProcThreadAttributeList': ([ptr, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)], w.BOOL),
        'UpdateProcThreadAttribute': ([ptr, w.DWORD, c.c_size_t, ptr, c.c_size_t, ptr, ptr], w.BOOL),
        'DeleteProcThreadAttributeList': ([ptr], None),
        'CreateProcessW': ([w.LPCWSTR, w.LPWSTR, ptr, ptr, w.BOOL, w.DWORD, ptr,
                            w.LPCWSTR, ptr, c.POINTER(ProcessInfo)], w.BOOL),
        'ResumeThread': ([handle], w.DWORD),
        'TerminateProcess': ([handle, w.UINT], w.BOOL),
        'WaitForSingleObject': ([handle, w.DWORD], w.DWORD),
        'GetExitCodeProcess': ([handle, c.POINTER(w.DWORD)], w.BOOL),
        'PeekNamedPipe': ([handle, ptr, w.DWORD, ptr, c.POINTER(w.DWORD), ptr], w.BOOL),
        'ReadFile': ([handle, ptr, w.DWORD, c.POINTER(w.DWORD), ptr], w.BOOL),
        'WriteFile': ([handle, ptr, w.DWORD, c.POINTER(w.DWORD), ptr], w.BOOL),
        'OpenProcess': ([w.DWORD, w.BOOL, w.DWORD], handle),
        'CloseHandle': ([handle], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        try:
            fn = getattr(kernel, name)
        except AttributeError as exc:
            raise OSError('ConPTY requires Windows 10 version 1809 or later') from exc
        fn.argtypes, fn.restype = args, result
    return kernel


def create_as_user(token, *arguments):
    security = c.WinDLL('advapi32', use_last_error=True)
    function = security.CreateProcessAsUserW
    function.argtypes = [w.HANDLE, w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p,
                         w.BOOL, w.DWORD, c.c_void_p, w.LPCWSTR, c.c_void_p,
                         c.POINTER(ProcessInfo)]
    function.restype = w.BOOL
    return function(int(token), *arguments)


def check(result, operation):
    if not result:
        error = c.get_last_error()
        raise OSError(error, f'{operation}: {c.FormatError(error)}')
    return result


def hresult(result, operation):
    if result < 0:
        raise OSError(f'{operation}: HRESULT 0x{result & 0xffffffff:08x}')


def size(columns, rows):
    if not (1 <= columns <= 32767 and 1 <= rows <= 32767):
        raise ValueError('terminal dimensions must be between 1 and 32767')
    return Coord(columns, rows)


def environment_block(environment):
    normalized = {}
    for key, value in environment.items():
        if not key or '=' in key or '\0' in key or '\0' in value:
            raise ValueError('invalid Windows environment entry')
        normalized[key.upper()] = (key, value)
    entries = ['='.join(normalized[key]) for key in sorted(normalized)]
    return c.create_unicode_buffer('\0'.join(entries) + '\0\0')
