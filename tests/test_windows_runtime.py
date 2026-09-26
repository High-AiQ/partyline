"""Shared adapter behavior on a bounded asynchronous native console."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from partyline.adapters.base import Adapter
from partyline.adapters.windows_runtime import WindowsRuntime, start
from partyline import launch, windows_server


class WindowsRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.adapter = Adapter({'id': 'probe', 'name': 'probe', 'cwd': '.', 'command': ['probe']},
                               AsyncMock(), AsyncMock())
        self.console = MagicMock()
        self.console.write = AsyncMock()
        self.console.close = AsyncMock()
        self.runtime = WindowsRuntime(self.adapter, self.console)
        self.adapter._windows = self.runtime

    async def test_shared_input_and_keys_keep_order_and_complete_receipts(self):
        pump = asyncio.create_task(self.runtime.write_loop())
        self.adapter.write_terminal(b'first')
        self.adapter.send_key('enter')
        await self.adapter._write_all(b'last')
        self.assertEqual([c.args[0] for c in self.console.write.await_args_list],
                         [b'first', b'\r', b'last'])
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        self.console.close.assert_awaited()

    async def test_failed_write_rejects_inflight_and_queued_receipts(self):
        self.console.write.side_effect = OSError('broken pipe')
        first = asyncio.create_task(self.runtime.write(b'first'))
        second = asyncio.create_task(self.runtime.write(b'second'))
        await asyncio.sleep(0)
        with self.assertRaisesRegex(OSError, 'broken pipe'):
            await self.runtime.write_loop()
        results = await asyncio.gather(first, second, return_exceptions=True)
        self.assertTrue(all(isinstance(r, OSError) for r in results))

    async def test_natural_close_wakes_idle_writer_and_cancelled_input_is_skipped(self):
        cancelled = asyncio.create_task(self.runtime.write(b'cancelled'))
        await asyncio.sleep(0)
        cancelled.cancel()
        await asyncio.gather(cancelled, return_exceptions=True)
        pump = asyncio.create_task(self.runtime.write_loop())
        await self.runtime.write(b'live')
        await self.runtime.close()
        await asyncio.wait_for(pump, 1)
        self.console.write.assert_awaited_once_with(b'live')
        self.console.close.assert_awaited_once()

    async def test_pending_input_is_bounded_and_closed_terminal_refuses_input(self):
        with self.assertRaises(OSError):
            self.runtime.write_nowait(b'x' * (1024 * 1024 + 1))
        for _ in range(64):
            self.runtime.write_nowait(b'x')
        with self.assertRaisesRegex(OSError, 'full'):
            self.runtime.write_nowait(b'x')
        await self.runtime.close()
        with self.assertRaisesRegex(OSError, 'closed'):
            await self.runtime.write(b'x')

    async def test_output_is_terminal_only_and_exit_resolves_readiness(self):
        self.console.read = AsyncMock(side_effect=[b'fixture output', b''])
        self.adapter.on_output = AsyncMock()
        await self.runtime.drain()
        self.adapter.on_output.assert_awaited_once_with(b'fixture output')
        self.adapter._post_to_chat.assert_not_awaited()
        self.console.wait = AsyncMock(return_value=7)
        await self.runtime.watch_exit()
        self.assertFalse(await self.adapter.wait_ready())
        self.adapter.on_status.assert_awaited_once_with('exited')
        self.assertIn('code 7', self.adapter._post_to_chat.call_args.args[-1])

    async def test_windows_start_uses_console_and_still_calls_fence(self):
        with patch('partyline.adapters.base.sys.platform', 'win32'), \
             patch('partyline.adapters.windows_runtime.windows_scope.prepare') as scope, \
             patch('partyline.adapters.base.fence.launch_argv', return_value=['fixture']) as fence, \
             patch('partyline.adapters.windows_runtime.WindowsConsole.spawn',
                   new=AsyncMock(return_value=self.console)) as spawn:
            self.console.read = AsyncMock(return_value=b'')
            self.console.wait = AsyncMock(return_value=0)
            scope.return_value.token = None
            await self.adapter.start()
            fence.assert_called_once_with(self.adapter)
            self.assertEqual(spawn.call_args.args[0], ['fixture'])
            await self.adapter.stop()
            await asyncio.gather(*self.adapter._tasks, return_exceptions=True)

    async def test_scope_is_removed_after_failed_spawn_and_after_job_shutdown(self):
        self.adapter.spawn_argv = ['fixture.exe']
        self.adapter.memory_limit = '128M'
        scope = MagicMock()
        with patch('partyline.adapters.windows_runtime.fence.backend', return_value='restricted-token'), \
             patch('partyline.adapters.windows_runtime.features.enabled', return_value=True), \
             patch('partyline.adapters.windows_runtime.windows_scope.prepare', return_value=scope), \
             patch('partyline.adapters.windows_runtime.WindowsConsole.spawn',
                   new=AsyncMock(side_effect=OSError('spawn refused'))) as spawn:
            with self.assertRaisesRegex(OSError, 'spawn refused'):
                await start(self.adapter, {})
            self.assertIs(spawn.call_args.kwargs['token'], scope.token)
            scope.close.assert_called_once()
        order = []
        self.console.close.side_effect = lambda **kwargs: order.append('job')
        scope.close.side_effect = lambda: order.append('permissions')
        runtime = WindowsRuntime(self.adapter, self.console, scope)
        await asyncio.gather(runtime.close(), runtime.close())
        self.assertEqual(order, ['job', 'permissions'])


class WindowsStartupTest(unittest.TestCase):
    def test_verified_job_wraps_server_and_is_closed_on_failure(self):
        with patch.object(windows_server, 'WindowsJob') as factory, \
             patch('partyline.server_memory.limit_bytes', return_value=123), \
             patch('partyline.bind.load_dotenv'):
            def fail(arguments):
                self.assertEqual(windows_server.breakaway_flags(), 0x1000000)
                raise RuntimeError('server stopped')
            callback = MagicMock(side_effect=fail)
            with self.assertRaisesRegex(RuntimeError, 'server stopped'):
                windows_server.serve(['--port', '8642'], callback)
            factory.assert_called_once_with(123, server=True)
            factory.return_value.assign_current_process.assert_called_once()
            factory.return_value.close.assert_called_once()
            self.assertEqual(windows_server.breakaway_flags(), 0)

    def test_launcher_delegates_windows_memory_setup(self):
        with patch.object(launch.sys, 'platform', 'win32'), \
             patch.object(windows_server, 'serve', return_value=0) as serve:
            self.assertEqual(launch.main(['--port', '8765']), 0)
            self.assertEqual(serve.call_args.args[0], ['--port', '8765'])


@unittest.skipUnless(sys.platform == 'win32', 'native adapter fixture')
class NativeWindowsAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_attachment_leaves_server_budget_but_helpers_stay_capped(self):
        script = '''import asyncio,ctypes as c,os,sys
from ctypes import wintypes as w
from partyline.windows_memory import WindowsJob
from partyline.windows_console import WindowsConsole
from partyline import windows_server
async def main():
    job=WindowsJob(128*1024**2,server=True)
    job.assign_current_process()
    windows_server._server_job=job
    child=None
    try:
        child=await WindowsConsole.spawn([sys.executable,'-c',
            'x=bytearray(160*1024**2)'],os.getcwd(),dict(os.environ),256*1024**2)
        inside=w.BOOL()
        assert job.api.IsProcessInJob(child.process.hProcess,job.handle,c.byref(inside))
        assert not inside.value, 'attachment inherited the smaller server budget'
        assert await asyncio.wait_for(child.wait(),20)==0
        import subprocess
        helper=subprocess.run([sys.executable,'-c',
            'try: x=bytearray(160*1024**2)\\nexcept MemoryError: raise SystemExit(0)\\n'
            'raise SystemExit(9)'],capture_output=True)
        assert helper.returncode==0,helper.stderr
    finally:
        if child: await child.close()
        windows_server._server_job=None
        job.close()
asyncio.run(main())
'''
        result = await asyncio.to_thread(subprocess.run, [sys.executable, '-c', script],
                                         capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)

    async def test_shared_adapter_starts_real_console_and_stops_descendants(self):
        from partyline.windows_private import secure_directory
        with tempfile.TemporaryDirectory() as cwd:
            root = Path(cwd).resolve()
            secure_directory(root)
            work, protected = root / 'work', root / 'protected'
            work.mkdir()
            protected.mkdir()
            secret = protected / 'data'
            secret.write_text('original')
            script = (
                'import pathlib,sys,time\n'
                'assert sys.stdin.isatty()\n'
                'pathlib.Path("allowed").write_text("ok")\n'
                'try: pathlib.Path(sys.argv[1]).unlink()\n'
                'except PermissionError: pass\n'
                'else: raise AssertionError("protected deletion allowed")\n'
                'print("TTY=True",flush=True);time.sleep(60)\n'
            )
            att = {'id': 'fixture', 'name': 'fixture', 'cwd': str(work),
                   'protected_roots': [str(protected)], 'command': [
                sys.executable, '-u', '-c',
                script, str(secret),
            ]}
            adapter = Adapter(att, AsyncMock(), AsyncMock())
            ready = asyncio.Event()
            async def output(data):
                if b'TTY=True' in data:
                    ready.set()
            adapter.on_output = output
            with patch('partyline.windows_scope.Path.home', return_value=root / 'home'), \
                 patch.dict(os.environ, PARTYLINE_PROCESS_MEMORY_LIMIT='128M'):
                await adapter.start()
                try:
                    await asyncio.wait_for(ready.wait(), 15)
                    self.assertTrue(adapter.alive())
                finally:
                    await adapter.stop()
                    await asyncio.gather(*adapter._tasks, return_exceptions=True)
                self.assertFalse(adapter.alive())
                self.assertEqual(secret.read_text(), 'original')
                self.assertEqual((work / 'allowed').read_text(), 'ok')
