import base64
import subprocess
import sys
import unittest
from unittest.mock import patch

from partyline.windows_shell import python_command
from partyline.adapters.bundled.claude.adapter import PartylineAdapter


class WindowsHookTest(unittest.TestCase):
    def test_script_and_interpreter_cannot_expand_in_the_hook_shell(self):
        script = 'print("$HOME & %PATH%")'
        with patch('partyline.windows_shell.sys.executable', "C:/one ' two/python.exe"):
            command = python_command(script)
        decoded = base64.b64decode(command.split()[-1]).decode('utf-16le')
        self.assertIn("'C:/one '' two/python.exe'", decoded)
        self.assertIn(script.encode().hex(), decoded)
        self.assertNotIn('%PATH%', decoded)

    def test_claude_windows_uses_native_http_hooks(self):
        with patch('partyline.adapters.bundled.claude.adapter.sys.platform', 'win32'):
            settings = PartylineAdapter._hook_settings('http://fixture.invalid/receipt')
        for event in ('Notification', 'UserPromptSubmit', 'Stop'):
            hook = settings['hooks'][event][0]['hooks'][0]
            self.assertEqual(hook, {'type': 'http', 'url': 'http://fixture.invalid/receipt', 'timeout': 5})

    @unittest.skipUnless(sys.platform == 'win32', 'native PowerShell/CMD hook command')
    def test_cmd_and_powershell_keep_literal_arguments_and_exit_status(self):
        command = python_command('print("%PATH% & $HOME"); raise SystemExit(7)')
        for prefix in (['cmd.exe', '/d', '/s', '/c'],
                       ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command']):
            result = subprocess.run([*prefix, command], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(result.stdout.strip(), '%PATH% & $HOME')
