import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from partyline.windows_command import resolve


class WindowsCommandTest(unittest.TestCase):
    def test_native_program_keeps_arguments_literal_and_path_case_insensitive(self):
        args = ['a & b', '%PATH%', '"quoted"', 'two\nlines']
        with patch('partyline.windows_command.shutil.which', return_value='tool.exe') as which:
            self.assertEqual(resolve(['tool', *args], {'Path': 'bin'}), ['tool.exe', *args])
            which.assert_called_once_with('tool', path='bin')

    def test_npm_shim_uses_node_and_never_shell_interpolation(self):
        with tempfile.TemporaryDirectory(prefix='npm shim ') as directory:
            root = Path(directory)
            script = root / 'node_modules' / 'fixture' / 'cli.js'
            script.parent.mkdir(parents=True)
            script.write_text('console.log(process.argv)')
            shim = root / 'fixture.cmd'
            shim.write_text('SET "_prog=%dp0%\\node.exe"\nSET "_prog=node"\n'
                            '"%_prog%"  "%dp0%\\node_modules\\fixture\\cli.js" %*\n')
            node = root / 'node.exe'
            node.touch()
            with patch('partyline.windows_command.shutil.which', return_value=str(shim)):
                self.assertEqual(resolve(['fixture', '%X% & "literal"'], os.environ),
                                 [str(node), str(script), '%X% & "literal"'])
            shim.write_text('@echo custom shell command %*')
            with patch('partyline.windows_command.shutil.which', return_value=str(shim)):
                with self.assertRaisesRegex(OSError, 'interpreter'):
                    resolve(['fixture'], os.environ)

    def test_missing_program_and_nul_fail_before_launch(self):
        with patch('partyline.windows_command.shutil.which', return_value=None):
            with self.assertRaisesRegex(OSError, 'not found'):
                resolve(['missing'], {})
        for argv in ([], ['bad\0.exe']):
            with self.assertRaises(ValueError):
                resolve(argv, {})
