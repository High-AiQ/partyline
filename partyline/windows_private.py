"""Owner-only connection files on NTFS, using handles and explicit DACLs."""

import json


def _user():
    import win32api
    import win32con
    import win32security as security
    token = security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        return security.GetTokenInformation(token, security.TokenUser)[0]
    finally:
        token.Close()


def _open(path, access):
    import win32con
    import win32file
    handle = win32file.CreateFile(
        str(path), access, win32con.FILE_SHARE_READ, None, win32con.OPEN_EXISTING,
        0x00200000 | win32con.FILE_FLAG_BACKUP_SEMANTICS, None,
    )
    if win32file.GetFileInformationByHandle(handle)[0] & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
        handle.Close()
        raise ValueError('private connection path is a reparse point')
    return handle


def secure_directory(path, *, directory=True):
    import win32con
    import win32security as security
    handle = _open(path, win32con.READ_CONTROL | win32con.WRITE_DAC | win32con.WRITE_OWNER)
    try:
        user = _user()
        acl = security.ACL()
        for sid in (user, security.CreateWellKnownSid(security.WinLocalSystemSid, None)):
            acl.AddAccessAllowedAceEx(security.ACL_REVISION, 3 if directory else 0,
                                     0x1f01ff, sid)
        information = (security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION
                       | security.OWNER_SECURITY_INFORMATION)
        security.SetSecurityInfo(handle, security.SE_FILE_OBJECT, information, user, None, acl, None)
    finally:
        handle.Close()


def load_connection(path):
    import win32con
    import win32file
    import win32security as security
    handle = _open(path, win32con.GENERIC_READ | win32con.READ_CONTROL)
    try:
        if win32file.GetFileInformationByHandle(handle)[0] & win32con.FILE_ATTRIBUTE_DIRECTORY:
            raise ValueError('connection path must be a regular file')
        descriptor = security.GetSecurityInfo(handle, security.SE_FILE_OBJECT,
                                              security.DACL_SECURITY_INFORMATION
                                              | security.OWNER_SECURITY_INFORMATION)
        user = _user()
        if descriptor.GetSecurityDescriptorOwner() != user:
            raise ValueError('connection file belongs to another user')
        acl = descriptor.GetSecurityDescriptorDacl()
        allowed = (user, security.CreateWellKnownSid(security.WinLocalSystemSid, None))
        if acl is None or any(acl.GetAce(i)[0][0] != 0 or acl.GetAce(i)[-1] not in allowed
                              for i in range(acl.GetAceCount())):
            raise ValueError('connection file is not private')
        if win32file.GetFileSize(handle) > 65536:
            raise ValueError('connection file is too large')
        _, data = win32file.ReadFile(handle, 65536)
        return json.loads(data)
    finally:
        handle.Close()
