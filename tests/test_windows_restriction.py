"""Native negative tests for the prospective Windows write-fence boundary."""

import asyncio
import os
from pathlib import Path
import sys
import tempfile
import unittest

from partyline.windows_restriction import create_token, can_access, edit_grant
from partyline.windows_console import WindowsConsole


@unittest.skipUnless(sys.platform == 'win32', 'native restricted-token access checks')
class RestrictedTokenTest(unittest.IsolatedAsyncioTestCase):
    async def test_token_writes_only_granted_tree_and_cannot_rewrite_protected_acl(self):
        import win32security as security
        from partyline.windows_private import _user, secure_directory
        with tempfile.TemporaryDirectory(prefix='partyline restriction ') as root:
            root = Path(root)
            allowed, protected = root / 'allowed', root / 'protected'
            allowed.mkdir()
            secure_directory(allowed)
            protected.write_text('protected', encoding='utf-8')
            # CI runs elevated; explicitly exercise ordinary user ownership too.
            security.SetNamedSecurityInfo(str(protected), security.SE_FILE_OBJECT,
                                         security.OWNER_SECURITY_INFORMATION, _user(), None, None, None)
            token, sid = create_token()
            self.addCleanup(token.Close)
            edit_grant(allowed, sid)
            try:
                self.assertTrue(can_access(token, allowed, 2))
                for permission in (2, 4, 0x10000, 0x40000, 0x80000):
                    self.assertFalse(can_access(token, protected, permission), hex(permission))
                self.assertFalse(can_access(token, root, 0x40), 'parent must not allow delete-child')
                code = (
                    'import os,pathlib,subprocess,sys,win32api,win32con\n'
                    'root=pathlib.Path(sys.argv[1]); (root/"allowed"/"new").write_text("yes")\n'
                    'try:\n (root/"protected").write_text("escaped")\n'
                    'except PermissionError: pass\n'
                    'else: raise AssertionError("protected write escaped")\n'
                    'try:\n win32api.OpenProcess(0x20|0x40000,False,int(sys.argv[2]))\n'
                    'except Exception: pass\n'
                    'else: raise AssertionError("unrestricted parent process writable")\n'
                    'print("FENCED",flush=True)\n'
                )
                console = await WindowsConsole.spawn(
                    [sys.executable, '-u', '-c', code, str(root), str(os.getpid())], str(allowed),
                    dict(os.environ), 128 * 1024**2, token=token,
                )
                try:
                    self.assertEqual(await asyncio.wait_for(console.wait(), 15), 0)
                    self.assertEqual((allowed / 'new').read_text(), 'yes')
                    self.assertEqual(protected.read_text(), 'protected')
                finally:
                    await console.close()
            finally:
                for path in allowed.rglob('*'):
                    edit_grant(path, sid, remove=True)
                edit_grant(allowed, sid, remove=True)
