"""Restricted-token primitives for native filesystem-fence validation.

No caller may treat token creation alone as proof of filesystem isolation.
The policy must verify protected objects with this token before launching code.
"""

import secrets
from contextlib import contextmanager
from pathlib import Path

from .windows_access import check


def create_token():
    import win32api
    import win32con
    import win32security as security

    original = security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_ALL_ACCESS)
    try:
        groups = security.GetTokenInformation(original, security.TokenGroups)
        logon = [sid for sid, attributes in groups if attributes & 0xc0000000 == 0xc0000000]
        if len(logon) != 1:
            raise OSError('Windows write fence requires an interactive logon session')
        identity = 'S-1-5-21-' + '-'.join(str(secrets.randbits(32)) for _ in range(3)) + '-1001'
        sid = security.ConvertStringSidToSid(identity)
        world = security.CreateWellKnownSid(security.WinWorldSid, None)
        # DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED. Do not include
        # the user SID: that would retain its unrestricted filesystem grants.
        token = security.CreateRestrictedToken(original, 0x0d, [], [], [
            (world, 0), (logon[0], 0), (sid, 0),
        ])
        return token, sid
    finally:
        original.Close()


def can_access(token, path, permission):
    import win32security as security

    descriptor = security.GetNamedSecurityInfo(
        str(path), security.SE_FILE_OBJECT,
        security.DACL_SECURITY_INFORMATION | security.OWNER_SECURITY_INFORMATION
        | security.GROUP_SECURITY_INFORMATION,
    )
    impersonation = security.DuplicateToken(token, security.SecurityImpersonation)
    try:
        return check(descriptor, impersonation, permission)
    finally:
        impersonation.Close()


@contextmanager
def _pinned(path):
    """Keep every ancestor from becoming a junction during the ACL operation."""
    import win32con
    import win32file
    handles = []
    try:
        for parent in reversed(Path(path).absolute().parents):
            handle = win32file.CreateFile(
                str(parent), 0x80,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE, None, win32con.OPEN_EXISTING,
                win32con.FILE_FLAG_BACKUP_SEMANTICS | 0x00200000, None,
            )
            handles.append(handle)
            if win32file.GetFileInformationByHandle(handle)[0] & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError(f'write grant traverses a reparse point: {parent}')
        yield
    finally:
        for handle in reversed(handles):
            handle.Close()


def edit_grant(path, sid, *, remove=False, permission=0x1301bf, deny=False, inherit=True):
    with _pinned(path):
        _edit_grant(path, sid, remove=remove, permission=permission, deny=deny, inherit=inherit)


def _edit_grant(path, sid, *, remove, permission, deny, inherit):
    """Change only our synthetic SID's ACE, on a pinned non-reparse object.

    SetKernelObjectSecurity avoids automatic propagation to existing children;
    callers explicitly walk those children without following junctions. New
    children inherit the ACE. The real user's ACEs and ownership remain intact.
    """
    import win32con
    import win32file
    import win32security as security

    handle = win32file.CreateFile(
        str(path), win32con.READ_CONTROL | win32con.WRITE_DAC,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
        None, win32con.OPEN_EXISTING,
        win32con.FILE_FLAG_BACKUP_SEMANTICS | 0x00200000, None,
    )
    try:
        attributes = win32file.GetFileInformationByHandle(handle)[0]
        if attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError(f'write grants cannot follow a reparse point: {path}')
        descriptor = security.GetSecurityInfo(handle, security.SE_FILE_OBJECT,
                                              security.DACL_SECURITY_INFORMATION)
        acl = descriptor.GetSecurityDescriptorDacl()
        if acl is None:
            raise OSError(f'write fence refuses an unrestricted DACL: {path}')
        for index in reversed(range(acl.GetAceCount())):
            ace = acl.GetAce(index)
            if ace[-1] == sid:
                acl.DeleteAce(index)
        if not remove:
            inheritance = 3 if inherit and attributes & win32con.FILE_ATTRIBUTE_DIRECTORY else 0
            if deny:
                # PyACL canonicalizes the ACL after adding an explicit deny,
                # placing it before allows while preserving other ACE types.
                acl.AddAccessDeniedAceEx(security.ACL_REVISION, inheritance, permission, sid)
            else:
                acl.AddAccessAllowedAceEx(security.ACL_REVISION, inheritance, permission, sid)
        descriptor.SetSecurityDescriptorDacl(True, acl, False)
        security.SetKernelObjectSecurity(handle, security.DACL_SECURITY_INFORMATION, descriptor)
    finally:
        handle.Close()
