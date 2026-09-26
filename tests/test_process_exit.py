import os
import shutil
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline import process_exit, process_memory
from partyline.memory_contracts import ProcessExit


class ExitEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.scope = process_exit.new_scope()

    def result(self, output, code=0):
        return subprocess.CompletedProcess([], code, output)

    def test_retains_and_reads_real_oom_evidence_despite_sigterm(self):
        with patch.object(process_exit.subprocess, 'run', return_value=self.result(
            'Result=oom-kill\nMemoryMax=4294967296\nMemoryPeak=4294967296\n')):
            evidence = process_exit.inspect_exit(self.scope, -15, '4G')
        self.assertEqual(evidence.reason, 'oom')
        self.assertEqual(evidence.peak_bytes, 4 * 1024**3)
        self.assertIn('confirmed out-of-memory', process_exit.exit_notice('worker', evidence))
        with patch.object(process_memory.shutil, 'which', return_value='systemd-run'):
            argv = process_memory.scope_argv(['tool'], '4G', unit=self.scope)
        self.assertIn(f'--unit={self.scope}', argv)
        self.assertNotIn('--collect', argv)
        self.assertIn('OOMPolicy=stop', argv)

    def test_never_infers_oom_from_signal_or_peak(self):
        for code in (-9, -15, 137, 1):
            with patch.object(process_exit.subprocess, 'run', return_value=self.result(
                'Result=success\nMemoryPeak=4294967296\n')):
                evidence = process_exit.inspect_exit(self.scope, code, '4G')
            self.assertEqual(evidence.reason, 'exit')
            self.assertNotIn('out-of-memory', process_exit.exit_notice('worker', evidence))

    def test_missing_malformed_or_unavailable_measurements(self):
        for result in (self.result('', 1), self.result(
            'Result=oom-kill\nMemoryPeak=18446744073709551615\nMemoryMax=bad\ninvalid')):
            with patch.object(process_exit.subprocess, 'run', return_value=result):
                evidence = process_exit.inspect_exit(self.scope, -15, '4G')
            self.assertIsNone(evidence.peak_bytes)
            self.assertEqual(evidence.limit_bytes, 4 * 1024**3)
        for error in (OSError('missing'), subprocess.TimeoutExpired('systemctl', 3)):
            with patch.object(process_exit.subprocess, 'run', side_effect=error):
                self.assertEqual(process_exit.inspect_exit(self.scope, -15, '4G').reason, 'exit')
                process_exit.release_scope(self.scope)
        with patch.object(process_exit.subprocess, 'run') as run:
            for scope in (None, 'other.scope', '--all'):
                self.assertEqual(process_exit.inspect_exit(scope, 125, '4G').reason, 'unverified')
                process_exit.release_scope(scope)
            run.assert_not_called()
        self.assertIn('could not be verified', process_exit.exit_notice(
            'worker', ProcessExit(code=125, reason='unverified', limit_bytes=1024)))

    def test_capped_runner_maps_scope_oom_to_137_and_releases_it(self):
        import runpy
        from pathlib import Path
        runner = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/capped-test'))
        function = runner['run_capped']
        with patch.dict(function.__globals__, {'systemd_available': lambda *_: True}), \
             patch.object(sys, 'platform', 'linux'), \
             patch.object(subprocess, 'run', side_effect=[self.result('', -15),
                                                        self.result('oom-kill\n'), self.result('')]) as run:
            self.assertEqual(function(['command'], 1024, {}), 137)
        self.assertIn('reset-failed', run.call_args.args[0])

    @unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('systemd-run')
                         and os.environ.get('XDG_RUNTIME_DIR'), 'requires user systemd')
    def test_kernel_oom_survives_launcher_exit_with_evidence(self):
        argv = process_memory.scope_argv(
            [sys.executable, '-c', 'x = bytearray(96 * 1024**2)'], '64M', unit=self.scope)
        try:
            result = subprocess.run(argv, capture_output=True, timeout=20)
            if result.returncode == 125 or b'Failed to connect' in result.stderr:
                self.skipTest('user manager or memory controller is unavailable')
            evidence = process_exit.inspect_exit(self.scope, result.returncode, '64M')
            self.assertEqual(evidence.reason, 'oom', result.stderr.decode(errors='replace'))
            self.assertEqual(evidence.limit_bytes, 64 * 1024**2)
        finally:
            process_exit.release_scope(self.scope)


class ExitReportingTest(unittest.IsolatedAsyncioTestCase):
    async def test_releases_evidence_only_after_reporting_or_planned_stop(self):
        events = []
        async def status(value):
            events.append(value)
        async def report(evidence):
            events.append(evidence.reason)
        adapter = SimpleNamespace(memory_scope=process_exit.new_scope(), memory_limit='4G',
                                  _stopping=False, on_status=status,
                                  att={'name': 'worker', 'on_process_exit': report}, post=AsyncMock())
        evidence = ProcessExit(code=-15, reason='oom', result='oom-kill', limit_bytes=4 * 1024**3)
        with patch.object(process_exit, 'inspect_exit', return_value=evidence), \
             patch.object(process_exit, 'release_scope') as release:
            await process_exit.report_exit(adapter, -15)
            self.assertEqual(events, ['exited', 'oom'])
            adapter._stopping = True
            await process_exit.report_exit(adapter, -15)
            self.assertEqual(events, ['exited', 'oom'])
            adapter._stopping = False
            adapter.att['on_process_exit'] = AsyncMock(side_effect=RuntimeError('report failed'))
            with self.assertRaises(RuntimeError):
                await process_exit.report_exit(adapter, -15)
            self.assertEqual(release.call_count, 2)
        adapter.post.assert_not_awaited()

    async def test_unavailable_diagnostics_keep_scope_for_later_inspection(self):
        adapter = SimpleNamespace(memory_scope=process_exit.new_scope(), memory_limit='4G',
                                  _stopping=False, on_status=AsyncMock(),
                                  att={'name': 'worker'}, post=AsyncMock())
        evidence = ProcessExit(code=-15, limit_bytes=1024)
        with patch.object(process_exit, 'inspect_exit', return_value=evidence), \
             patch.object(process_exit, 'release_scope') as release:
            await process_exit.report_exit(adapter, -15)
        release.assert_not_called()

    async def test_attachment_override_is_used_at_spawn(self):
        from tests.test_adapter_base import Recorder
        adapter = Recorder(['unused'])
        adapter.att['memory_limit'] = '6G'
        with patch.object(process_memory, 'scope_argv', side_effect=RuntimeError('before spawn')) as scope:
            with self.assertRaises(RuntimeError):
                await adapter.start()
        self.assertEqual(scope.call_args.args[1], '6G')
        if sys.platform.startswith('linux'):
            self.assertTrue(process_exit.SCOPE.fullmatch(adapter.memory_scope))
        else:
            self.assertIsNone(adapter.memory_scope)

    async def test_windows_unknown_exit_does_not_claim_memory_cause(self):
        adapter = SimpleNamespace(memory_limit='4G', _stopping=False,
                                  on_status=AsyncMock(), att={'name': 'worker'}, post=AsyncMock())
        with patch.object(process_exit.subprocess, 'run', new=Mock()) as run:
            await process_exit.report_exit(adapter, 3)
        run.assert_not_called()
        adapter.post.assert_awaited_once_with('system', 'system', 'worker exited (code 3)')
