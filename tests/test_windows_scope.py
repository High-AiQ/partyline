from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from partyline import windows_scope


class WindowsScopeTest(unittest.TestCase):
    def test_private_temporary_directory_and_serialized_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            cwd = root / 'work'
            cwd.mkdir()
            database = root / 'partyline.db'
            database.touch()
            adapter = SimpleNamespace(kind='codex', att={
                'id': 'fixture', 'cwd': str(cwd), 'db_paths': [str(database)],
            })
            environment = {'CODEX_HOME': str(root / 'private-codex')}
            with patch.object(windows_scope.Path, 'home', return_value=root), \
                 patch.object(windows_scope, 'WindowsFence') as policy:
                scope = windows_scope.prepare(adapter, environment)
                writable, protected, readable = policy.call_args.args
                self.assertIn(cwd, writable)
                self.assertIn(root / 'private-codex', writable)
                self.assertEqual(protected, [str(database)])
                self.assertTrue(readable)
                self.assertTrue(Path(environment['TEMP']).is_dir())
                self.assertNotEqual(environment['TEMP'], directory)
                scope.close()
                policy.return_value.close.assert_called_once()

    def test_cli_state_cannot_widen_scope_inside_a_protected_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            adapter = SimpleNamespace(kind='grok', att={
                'id': 'fixture', 'cwd': str(root), 'db_paths': [str(root / '.grok' / 'db')],
            })
            with patch.object(windows_scope.Path, 'home', return_value=root):
                with self.assertRaisesRegex(OSError, 'overlaps'):
                    windows_scope.prepare(adapter, {})
                self.assertFalse((root / '.grok').exists())
                adapter.att['id'] = '../escape'
                with self.assertRaises(ValueError):
                    windows_scope.prepare(adapter, {})
