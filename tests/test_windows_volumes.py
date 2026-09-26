import unittest
from unittest.mock import MagicMock, patch

from partyline import windows_volumes


class WindowsVolumeTest(unittest.TestCase):
    def test_local_acl_volume_is_checked_once(self):
        api = MagicMock()
        api.GetDriveTypeW.return_value = 3
        def volume(*args):
            args[5]._obj.value = 8
            return 1
        api.GetVolumeInformationW.side_effect = volume
        with patch.object(windows_volumes.c, 'WinDLL', return_value=api, create=True):
            windows_volumes.validate(['C:/work', 'c:/database'])
        api.GetVolumeInformationW.assert_called_once()

    def test_unc_mapped_drives_and_filesystems_without_acls_are_refused(self):
        api = MagicMock()
        with patch.object(windows_volumes.c, 'WinDLL', return_value=api, create=True):
            with self.assertRaisesRegex(OSError, 'local drive'):
                windows_volumes.validate(['\\\\server\\share\\project'])
            api.GetDriveTypeW.return_value = 4
            with self.assertRaisesRegex(OSError, 'network drives'):
                windows_volumes.validate(['Z:/project'])
            api.GetDriveTypeW.return_value = 3
            with self.assertRaisesRegex(OSError, 'filesystem ACLs'):
                windows_volumes.validate(['C:/project'])
