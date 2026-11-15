"""WinVerifyTrust Authenticode seam; ctypes layouts remain at module scope."""
import ctypes as C
from ctypes import wintypes as W
import uuid


GuidBytes = C.c_ubyte * 16


class GUID(C.Structure):
    _fields_ = [("data", GuidBytes)]


class FileInfo(C.Structure):
    _fields_ = [("size", W.DWORD), ("path", W.LPCWSTR), ("file", W.HANDLE), ("subject", C.c_void_p)]


class TrustData(C.Structure):
    _fields_ = [("size", W.DWORD), ("policy", C.c_void_p), ("sip", C.c_void_p),
                ("ui", W.DWORD), ("revocation", W.DWORD), ("choice", W.DWORD),
                ("info", C.c_void_p), ("action", W.DWORD), ("state", W.HANDLE),
                ("url", W.LPCWSTR), ("flags", W.DWORD), ("context", W.DWORD),
                ("settings", C.c_void_p)]


def verify(path, library=None):
    library = library or C.WinDLL("wintrust", use_last_error=True)
    function = library.WinVerifyTrust
    function.argtypes = [W.HWND, C.POINTER(GUID), C.POINTER(TrustData)]
    function.restype = C.c_long
    action = GUID(GuidBytes.from_buffer_copy(
        uuid.UUID("00aac56b-cd44-11d0-8cc2-00c04fc295ee").bytes_le))
    info = FileInfo(size=C.sizeof(FileInfo), path=str(path))
    data = TrustData(size=C.sizeof(TrustData), ui=2, revocation=1, choice=1,
                     info=C.cast(C.pointer(info), C.c_void_p), action=1)
    try:
        return function(None, C.byref(action), C.byref(data)) == 0
    finally:
        data.action = 2  # WTD_STATEACTION_CLOSE, including failed verification
        function(None, C.byref(action), C.byref(data))
