"""Real native-console interaction, suspend-before-cap, and process-tree cleanup."""

import asyncio
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from partyline import windows_console_api as win
from partyline.windows_console import WindowsConsole
from partyline.windows_memory import WindowsJob


class ConsoleArgumentsTest(unittest.TestCase):
    def test_split_and_repeated_terminal_queries_receive_replies(self):
        with patch.object(win, 'api'):
            console = WindowsConsole()
        console._stream.feed(b'\x1b[')
        self.assertEqual(console._responses, [])
        console._stream.feed(b'c')
        self.assertEqual(console._responses, ['\x1b[?6c'])
        console._responses.clear()
        console._stream.feed(b'\x1b[6n')
        self.assertEqual(console._responses, ['\x1b[1;1R'])

    def test_dimensions_are_checked_before_native_calls(self):
        for columns, rows in ((0, 40), (80, -1), (32768, 40)):
            with self.assertRaises(ValueError):
                win.size(columns, rows)
        self.assertEqual((win.size(80, 25).X, win.size(80, 25).Y), (80, 25))

    def test_environment_is_unicode_case_insensitive_and_literal(self):
        block = win.environment_block({'Path': 'old', 'PATH': 'new', 'VALUE': '$path %PATH% ☃'})
        self.assertIn('PATH=new\0VALUE=$path %PATH% ☃\0\0', block[:])
        self.assertNotIn('old', block[:])
        for env in ({'': 'x'}, {'x=y': 'z'}, {'x': 'a\0b'}):
            with self.assertRaises(ValueError):
                win.environment_block(env)

    def test_native_api_is_not_loaded_elsewhere(self):
        with patch.object(win.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(OSError, 'native Windows'):
                win.api()
        with self.assertRaisesRegex(OSError, 'HRESULT'):
            win.hresult(-1, 'probe')
        win.hresult(0, 'probe')


@unittest.skipUnless(sys.platform == 'win32', 'requires native ConPTY')
class NativeConsoleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='partyline conpty ')
        self.addCleanup(self.directory.cleanup)

    async def spawn(self, code, *args):
        diagnostic = str(Path(self.directory.name, 'fixture-diagnostic'))
        code = (
            'import pathlib,traceback,sys\n'
            f'diagnostic=pathlib.Path({diagnostic!r})\n'
            'diagnostic.write_text(repr((sys.stdin,sys.stdout,sys.stderr)),encoding="utf-8")\n'
            'try:\n exec(' + repr(code) + ')\n'
            'except BaseException:\n diagnostic.write_text(traceback.format_exc(),encoding="utf-8"); raise\n'
        )
        terminal = await WindowsConsole.spawn(
            [sys.executable, '-u', '-c', code, *args], self.directory.name,
            dict(os.environ, PARTYLINE_CONPTY_PROBE='$path %PATH% ☃'), 128 * 1024**2,
        )
        self.addAsyncCleanup(terminal.close)
        return terminal

    async def until(self, terminal, marker):
        output = b''
        async def collect():
            nonlocal output
            while marker not in output:
                chunk = await terminal.read()
                self.assertTrue(chunk, output.decode(errors='replace'))
                output = (output + chunk)[-1024 * 1024:]
            return output
        try:
            return await asyncio.wait_for(collect(), 15)
        except TimeoutError:
            diagnostic = Path(self.directory.name, 'fixture-diagnostic')
            detail = diagnostic.read_text(encoding='utf-8') if diagnostic.exists() else 'code never started'
            self.fail(f'console timed out: exit={terminal.poll()}, output={output!r}, fixture={detail}')

    async def test_real_console_resize_input_and_literal_environment(self):
        code = (
            "import os,sys; print('TTY='+str(sys.stdin.isatty()),flush=True); "
            "print('ARG='+sys.argv[1],flush=True); "
            "print('ENV='+os.environ['PARTYLINE_CONPTY_PROBE'],flush=True)\n"
            "for line in sys.stdin:\n"
            " if line.strip()=='size':\n"
            "  size=os.get_terminal_size(); print(f'SIZE={size.columns}x{size.lines}',flush=True)\n"
            " elif line.strip()=='exit': break\n"
        )
        terminal = await self.spawn(code, 'a"b $path %PATH%')
        output = await self.until(terminal, 'ENV=$path %PATH% ☃'.encode())
        self.assertIn(b'TTY=True', output)
        self.assertIn(b'ARG=a"b $path %PATH%', output)
        await terminal.resize(90, 30)
        await terminal.write(b'size\r')
        await self.until(terminal, b'SIZE=90x30')
        await terminal.write(b'exit\r')
        self.assertEqual(await asyncio.wait_for(terminal.wait(), 10), 0)
        await asyncio.wait_for(terminal.close(), 8)
        self.assertEqual(await terminal.read(), b'')
        self.assertEqual(await terminal.read(), b'')

    async def test_console_child_has_memory_limit_and_descendants_die_on_close(self):
        code = (
            "import subprocess,sys,time\n"
            "try:\n held=bytearray(192*1024**2); print('UNBOUNDED',flush=True)\n"
            "except MemoryError:\n print('BLOCKED',flush=True)\n"
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(600)']); "
            "print('CHILD='+str(child.pid)+' END',flush=True); time.sleep(600)"
        )
        terminal = await self.spawn(code)
        output = await self.until(terminal, b' END')
        self.assertIn(b'BLOCKED', output)
        child_pid = int(re.search(rb'CHILD=(\d+) END', output).group(1))
        handle = win.check(terminal.api.OpenProcess(0x100000, False, child_pid), 'OpenProcess')
        try:
            self.assertEqual(terminal.api.WaitForSingleObject(handle, 0), 258)
            await asyncio.wait_for(terminal.close(), 8)
            self.assertEqual(terminal.api.WaitForSingleObject(handle, 2000), 0)
        finally:
            terminal.api.CloseHandle(handle)

    async def test_failed_job_assignment_never_executes_child_code(self):
        marker = Path(self.directory.name, 'should-not-exist')
        code = f'from pathlib import Path; Path({str(marker)!r}).write_text("escaped")'
        with patch.object(WindowsJob, 'assign_process', side_effect=OSError('assignment denied')):
            with self.assertRaisesRegex(OSError, 'assignment denied'):
                await asyncio.wait_for(self.spawn(code), 10)
        self.assertFalse(marker.exists())
