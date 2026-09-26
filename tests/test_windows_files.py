from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from partyline.adapters.session_seed import seed


class SessionSeedTest(unittest.TestCase):
    def test_windows_copies_auth_and_resume_without_symlink_privileges(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source', root / 'private'
            source.mkdir()
            (source / 'auth.json').write_text('fixture credentials')
            with patch('partyline.adapters.session_seed.sys.platform', 'win32'), \
                 patch('partyline.adapters.session_seed.os.symlink', side_effect=AssertionError):
                seed(source, target)
                seed(source / 'auth.json', root / 'auth-copy')
                seed(root / 'missing', root / 'optional')
                (target / 'auth.json').write_text('private update')
                seed(source, target)
            self.assertEqual((target / 'auth.json').read_text(), 'private update')
            self.assertEqual((source / 'auth.json').read_text(), 'fixture credentials')
            self.assertEqual((root / 'auth-copy').read_text(), 'fixture credentials')
            self.assertFalse((root / 'optional').exists())


@unittest.skipUnless(sys.platform == 'win32', 'native handle-based file reads')
class WindowsFileTest(unittest.TestCase):
    def test_bounded_regular_file_and_junction_refusal(self):
        from partyline.windows_files import read_regular
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'source'
            source.mkdir()
            data = source / 'prompt_1.txt'
            data.write_bytes(b'fixture')
            self.assertEqual(read_regular(data, 100), b'fixture')
            with self.assertRaises(OSError):
                read_regular(data, 3)
            with self.assertRaises(OSError):
                read_regular(source, 100)
            junction = root / 'junction'
            subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(source)],
                           capture_output=True, check=True)
            try:
                with self.assertRaisesRegex(OSError, 'reparse'):
                    read_regular(junction / data.name, 100)
            finally:
                junction.rmdir()
