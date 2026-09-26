"""Call Windows' access checker; pywin32 does not expose this API."""

import ctypes as c
from ctypes import wintypes as w


def check(descriptor, token, permission):
    api = c.WinDLL('advapi32', use_last_error=True)
    api.AccessCheck.argtypes = [c.c_void_p, w.HANDLE, w.DWORD, c.c_void_p,
                               c.c_void_p, c.POINTER(w.DWORD), c.POINTER(w.DWORD),
                               c.POINTER(w.BOOL)]
    api.AccessCheck.restype = w.BOOL
    sd = c.create_string_buffer(bytes(descriptor))
    mapping = (w.DWORD * 4)(0x120089, 0x120116, 0x1200a0, 0x1f01ff)
    length, granted, allowed = w.DWORD(1024), w.DWORD(), w.BOOL()
    privileges = c.create_string_buffer(length.value)
    for _ in range(2):
        if api.AccessCheck(sd, int(token), permission, mapping, privileges,
                           c.byref(length), c.byref(granted), c.byref(allowed)):
            return bool(allowed.value)
        error = c.get_last_error()
        if error != 122 or not 0 < length.value <= 65536:
            raise c.WinError(error)
        privileges = c.create_string_buffer(length.value)
    raise OSError('Windows access-check privilege buffer did not stabilize')
