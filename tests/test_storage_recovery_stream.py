"""Recovery accounting accepts many names and a filename split between reads."""

from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from partyline.storage_recovery_space import RESERVE, RecoverySpaceError, require_space


class NameStream(BytesIO):
    def __init__(self):
        super().__init__()
        self.chunks = iter([b'a\0' * 10000 + b'last-', b'file\0'])

    def read(self, size):
        return next(self.chunks, b'')


class RecoveryStreamTest(unittest.TestCase):
    def test_large_chunk_and_partial_name_are_counted_without_losing_tail(self):
        process = SimpleNamespace(stdout=NameStream(), wait=lambda **kw: 0, poll=lambda: 0)
        from unittest.mock import MagicMock
        manager = MagicMock()
        manager.__enter__.return_value = process
        paths = []

        def info(path):
            paths.append(path)
            return SimpleNamespace(st_mode=0o100644, st_size=1)

        with patch('subprocess.Popen', return_value=manager), \
             patch('os.lstat', side_effect=info), \
             patch('shutil.disk_usage', return_value=SimpleNamespace(free=RESERVE + 10000)):
            with self.assertRaises(RecoverySpaceError):
                require_space('/owner', '/tree')
        self.assertEqual(len(paths), 10001)
        self.assertTrue(paths[-1].endswith('last-file'))
