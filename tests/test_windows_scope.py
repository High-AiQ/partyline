import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
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


@unittest.skipUnless(sys.platform == 'win32', 'native complete attachment permissions')
class NativeWindowsScopeTest(unittest.IsolatedAsyncioTestCase):
    async def test_connection_is_readable_but_not_writable_by_its_attachment(self):
        from partyline.windows_console import WindowsConsole
        from partyline.windows_private import secure_directory
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            secure_directory(root)
            work = root / 'work'
            work.mkdir()
            database = root / 'database'
            database.touch()
            connections = root / 'connections'
            connections.mkdir()
            secure_directory(connections)
            connection = connections / 'fixture.json'
            connection.write_text(json.dumps({'token': 'fixture'}))
            secure_directory(connection, directory=False)
            hooks = root / 'hooks'
            hooks.mkdir()
            secure_directory(hooks)
            hook = hooks / 'grok-turn-fixture.json'
            hook.write_text('hook fixture')
            script = (
                'import pathlib,sys\n'
                'from partyline.windows_private import load_connection\n'
                'assert load_connection(sys.argv[1])["token"]=="fixture"\n'
                'assert pathlib.Path(sys.argv[2]).read_text()=="hook fixture"\n'
                'try:\n pathlib.Path(sys.argv[1]).write_text("changed")\n'
                'except PermissionError: pass\n'
                'else: raise AssertionError("credential file writable")\n'
            )
            command = [sys.executable, '-u', '-c', script, str(connection), str(hook)]
            adapter = SimpleNamespace(kind='grok', spawn_argv=command, att={
                'id': 'fixture', 'cwd': str(work), 'db_paths': [str(database)],
                'grok_hooks_dir': str(hooks), 'grok_hooks_paths': str(root / 'registry'),
                '_agent_connection_file': str(connection),
            })
            environment = dict(os.environ)
            with patch.object(windows_scope.Path, 'home', return_value=root):
                scope = await asyncio.to_thread(windows_scope.prepare, adapter, environment)
            try:
                console = await WindowsConsole.spawn(command, str(work), environment,
                                                      256 * 1024**2, token=scope.token)
                output = bytearray()
                async def drain():
                    while data := await console.read():
                        output.extend(data)
                reader = asyncio.create_task(drain())
                try:
                    result = await asyncio.wait_for(console.wait(), 30)
                finally:
                    await console.close(preserve_output=True)
                    await reader
                self.assertEqual(result, 0, output.decode(errors='replace'))
            finally:
                await asyncio.to_thread(scope.close)
