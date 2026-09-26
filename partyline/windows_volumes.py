"""Require local filesystems that persist Windows security descriptors."""

import ctypes as c
from ctypes import wintypes as w
import ntpath


def validate(paths):
    api = c.WinDLL('kernel32', use_last_error=True)
    api.GetDriveTypeW.argtypes, api.GetDriveTypeW.restype = [w.LPCWSTR], w.UINT
    api.GetVolumeInformationW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD, c.c_void_p,
                                         c.c_void_p, c.POINTER(w.DWORD), w.LPWSTR, w.DWORD]
    api.GetVolumeInformationW.restype = w.BOOL
    checked = set()
    for path in paths:
        drive = ntpath.splitdrive(str(path))[0]
        if drive.startswith('\\\\?\\'):
            drive = drive[4:]
        if len(drive) != 2 or drive[1] != ':':
            raise OSError(f'Windows write fence requires a local drive: {path}')
        root = drive.upper() + '\\'
        if root in checked:
            continue
        checked.add(root)
        if api.GetDriveTypeW(root) not in (2, 3, 6):
            raise OSError(f'Windows write fence does not support network drives: {root}')
        flags = w.DWORD()
        if not api.GetVolumeInformationW(root, None, 0, None, None, c.byref(flags), None, 0):
            raise c.WinError(c.get_last_error())
        if not flags.value & 8:  # FILE_PERSISTENT_ACLS
            raise OSError(f'Windows write fence requires filesystem ACLs: {root}')
