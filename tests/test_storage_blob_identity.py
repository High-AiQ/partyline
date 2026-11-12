"""Content hashing tolerates reads but refuses concurrent content changes."""

from pathlib import Path
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from partyline.storage_orphan import blob


class BlobIdentityTest(unittest.TestCase):
    def test_read_access_timestamp_change_is_not_a_content_change(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'file'
            path.write_bytes(b'content')
            before = os.lstat(path)
            attrs = {name: getattr(before, name) for name in (
                'st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_atime_ns')}
            attrs['st_atime_ns'] += 100
            lstat = os.lstat

            def changed(after):
                calls = 0

                def inspect(name, *args, **kwargs):
                    nonlocal calls
                    if os.fspath(name) == os.fspath(path):
                        calls += 1
                        return before if calls == 1 else after
                    return lstat(name, *args, **kwargs)
                return inspect

            with patch('os.lstat', side_effect=changed(SimpleNamespace(**attrs))):
                oid, mode = blob(path, 'sha1')
            self.assertEqual(len(oid), 40)
            self.assertEqual(mode, '100644')
            attrs['st_mtime_ns'] += 100
            with patch('os.lstat', side_effect=changed(SimpleNamespace(**attrs))):
                with self.assertRaisesRegex(ValueError, 'changed while hashing'):
                    blob(path, 'sha1')
