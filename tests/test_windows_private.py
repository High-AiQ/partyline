import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from partyline import windows_private as private


class WindowsPrivateFileTest(unittest.TestCase):
    def setUp(self):
        self.handle = MagicMock()
        self.descriptor = MagicMock()
        self.descriptor.GetSecurityDescriptorOwner.return_value = 'user'
        self.acl = self.descriptor.GetSecurityDescriptorDacl.return_value
        self.acl.GetAceCount.return_value = 1
        self.acl.GetAce.return_value = ((0, 0), 0x1f01ff, 'user')
        self.security = MagicMock()
        self.security.GetSecurityInfo.return_value = self.descriptor
        self.security.CreateWellKnownSid.return_value = 'system'
        self.file = MagicMock()
        self.file.GetFileInformationByHandle.return_value = (0,)
        self.file.GetFileSize.return_value = 2
        self.file.ReadFile.return_value = (0, b'{}')
        constants = SimpleNamespace(GENERIC_READ=1, READ_CONTROL=2, WRITE_DAC=4, WRITE_OWNER=8,
                                    FILE_ATTRIBUTE_DIRECTORY=16, FILE_ALL_ACCESS=0x1f01ff)
        modules = patch.dict(sys.modules, win32con=constants, win32security=self.security,
                             win32file=self.file)
        modules.start()
        self.addCleanup(modules.stop)
        for name, result in (('_user', 'user'), ('_open', self.handle)):
            item = patch.object(private, name, return_value=result)
            item.start()
            self.addCleanup(item.stop)

    def test_private_file_is_parsed_and_handle_closed(self):
        self.assertEqual(private.load_connection('fixture'), {})
        self.handle.Close.assert_called_once()

    def test_public_or_foreign_owned_credentials_are_refused(self):
        self.descriptor.GetSecurityDescriptorOwner.return_value = 'stranger'
        with self.assertRaisesRegex(ValueError, 'another user'):
            private.load_connection('fixture')
        self.descriptor.GetSecurityDescriptorOwner.return_value = 'user'
        self.acl.GetAce.return_value = ((0, 0), 1, 'everyone')
        with self.assertRaisesRegex(ValueError, 'not private'):
            private.load_connection('fixture')
        self.file.ReadFile.assert_not_called()

    def test_directory_and_oversized_files_are_rejected(self):
        self.file.GetFileInformationByHandle.return_value = (16,)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            private.load_connection('fixture')
        self.file.GetFileInformationByHandle.return_value = (0,)
        self.file.GetFileSize.return_value = 65537
        with self.assertRaisesRegex(ValueError, 'too large'):
            private.load_connection('fixture')

    def test_only_user_and_system_receive_acl_entries(self):
        private.secure_directory('fixture')
        acl = self.security.ACL.return_value
        self.assertEqual([call.args[-1] for call in acl.AddAccessAllowedAceEx.call_args_list],
                         ['user', 'system'])
        self.security.SetSecurityInfo.assert_called_once()
        self.handle.Close.assert_called_once()


@unittest.skipUnless(sys.platform == 'win32', 'native NTFS permissions')
class NativeWindowsPrivateFileTest(unittest.TestCase):
    def test_private_credentials_roundtrip_and_other_sid_is_rejected(self):
        import win32security as security
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, 'connections')
            root.mkdir()
            private.secure_directory(root)
            file = root / 'fixture.json'
            file.write_text(json.dumps({'token': 'fixture'}))
            private.secure_directory(file, directory=False)
            self.assertEqual(private.load_connection(file), {'token': 'fixture'})
            descriptor = security.GetNamedSecurityInfo(str(file), security.SE_FILE_OBJECT,
                                                       security.DACL_SECURITY_INFORMATION)
            acl = descriptor.GetSecurityDescriptorDacl()
            acl.AddAccessAllowedAce(security.ACL_REVISION, 0x120089,
                                    security.CreateWellKnownSid(security.WinWorldSid, None))
            security.SetNamedSecurityInfo(str(file), security.SE_FILE_OBJECT,
                                         security.DACL_SECURITY_INFORMATION, None, None, acl, None)
            with self.assertRaisesRegex(ValueError, 'not private'):
                private.load_connection(file)
