"""Provider diagnostics use temporary logs only; no installed CLI or live DB."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline.adapters.bundled.opencode.provider_log import ProviderLog, safe_cause, fields
from partyline.adapters.bundled.opencode.v2 import PartylineAdapter
from partyline.orchestrator_stall import settle
from partyline.provider_errors import provider_error_callback


class ProviderLogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'opencode.log'
        self.path.write_text('old log that must never be replayed\n')
        self.log = ProviderLog(self.path, '[partyline-claim: ours]', '/work/one')

    def append(self, run='aa', level='INFO', message='cli starting', **extra):
        if isinstance(extra.get('args'), list):
            extra['args'] = json.dumps(extra['args'], separators=(',', ':'))
        data = dict(run=run, level=level, message=message, **extra)
        with self.path.open('a') as stream:
            stream.write(' '.join(f'{k}={json.dumps(v)}' for k, v in data.items()) + '\n')

    def bind(self):
        self.append(args=['--prompt', '[partyline-claim: ours] message="decoy" run=bb'])

    async def test_interleaved_runs_redaction_dedup_and_stall(self):
        self.append(run='bb', args='--prompt [partyline-claim: theirs]')
        self.bind()
        self.append(run='bb', level='ERROR', message='Failed to drain Session', cause='secret')
        self.append(message='Failed to drain Session', cause='INFO is not a failure')
        self.assertEqual(self.log.poll(), [])
        post = AsyncMock()
        att = dict(id='a', name='impl', conv_id='line', command=[], cwd='/work')
        adapter = PartylineAdapter(att, post, AsyncMock())
        adapter._provider_log = self.log
        self.append(level='ERROR', message='Failed to drain Session',
                    cause='AI.Error: Account customer@example.test sk-secret is suspended\n at secret')
        self.append(level='ERROR', message='Failed to drain Session',
                    cause='AI.Error: Account other is suspended')
        adapter._busy = True
        with patch("partyline.adapters.bundled.opencode.v2.receipt",
                   new_callable=AsyncMock) as receipt:
            await adapter._poll_provider()
        receipt.assert_awaited_once_with(att, "Stop")
        self.assertFalse(adapter._busy)
        self.assertEqual(post.await_count, 1)
        notice = post.call_args.args[2]
        self.assertIn('model provider error — account suspended', notice)
        for secret in ('customer', 'example.test', 'sk-secret', 'other'):
            self.assertNotIn(secret, notice)
        self.assertTrue(adapter.provider_failed)
        runtime = SimpleNamespace(live={'a': adapter}, db=Mock())
        with patch('partyline.orchestrator_stall.candidate') as candidate:
            await settle(runtime, att)
            candidate.assert_not_called()
        await adapter._poll_provider()
        self.assertEqual(post.await_count, 1)

    def test_literal_quoted_args_from_reported_log_format(self):
        fixture = Path(__file__).parent / 'fixtures/transcripts/opencode-v2/provider-log-quoted.log'
        excerpt = fixture.read_text()
        parent = fields(excerpt.splitlines()[1])
        self.assertEqual(parent['args'], '["serve","--stdio","--port","0"]')
        self.assertIsInstance(parent['args'], str)  # Logfmt decodes only the outer string.
        with self.path.open('a') as stream:
            stream.write(excerpt)
        self.assertEqual(self.log.poll(), [('account suspended [details redacted]', True)])
        self.assertEqual(self.log.server_run, '4708f720')

    def test_malformed_string_args_are_ignored(self):
        self.bind()
        self.append(message='spawning process', args='[not json', cwd='/work/one')
        self.append(run='child', args=['serve', '--stdio', '--port', '0'])
        self.append(run='child', message='spawning process', cwd='/work/one')
        self.append(run='child', level='ERROR', message='Failed to drain Session', cause='quota')
        self.assertEqual(self.log.poll(), [])
        self.assertIsNone(self.log.server_run)

    async def test_interleaved_tuis_and_standalone_servers(self):
        other = ProviderLog(self.path, '[partyline-claim: theirs]', '/work/two')
        fixture = Path(__file__).parent / 'fixtures/transcripts/opencode-v2/provider-log.log'
        lines = fixture.read_text().splitlines(keepends=True)
        with self.path.open('a') as stream:
            stream.writelines(lines[:9])
        self.assertEqual(self.log.poll(), [])
        self.assertEqual(other.poll(), [('quota or rate limit exceeded [details redacted]', True)])
        self.assertIsNone(self.log.server_run)
        with self.path.open('a') as stream:
            stream.writelines(lines[9:])
        post = AsyncMock()
        adapter = PartylineAdapter(dict(id='a', name='impl', command=[], cwd='/work/one'),
                                   post, AsyncMock())
        adapter._provider_log = self.log
        await adapter._poll_provider()
        self.assertEqual(self.log.server_run, 'aaaaaa02')
        self.assertEqual(other.server_run, 'bbbbbb02')
        self.assertEqual(other.poll(), [])
        self.assertEqual(post.await_count, 2)  # One server cause, one TUI cause.
        self.assertTrue(adapter.provider_failed)
        self.assertIn('account suspended', post.await_args_list[0].args[2])
        self.assertNotIn('private', str(post.await_args_list))
        self.assertNotIn('secret', str(post.await_args_list))
        self.assertEqual(self.log.poll(), [])
        self.path.rename(self.path.with_suffix('.rotated'))
        self.path.write_text('')
        self.append(run='aaaaaa02', level='ERROR', message='Failed to drain Session',
                    cause='invalid API key private-token')
        self.assertEqual(self.log.poll(), [('authentication failed [details redacted]', True)])
        self.assertEqual(other.poll(), [])

    def test_server_requires_parent_spawn_and_first_cwd_confirmation(self):
        self.bind()
        self.append(run='child', args=['serve', '--stdio', '--port', '0'])
        self.append(run='child', message='spawning process', cwd='/work/one')
        self.append(run='child', level='ERROR', message='Failed to drain Session', cause='quota')
        self.assertEqual(self.log.poll(), [])
        self.assertIsNone(self.log.server_run)
        self.append(message='spawning process', args=['serve', '--stdio', '--port', '0'],
                    cwd='/work/one')
        self.append(run='unrelated', args=['serve', '--stdio', '--port', '0'])
        self.append(run='unrelated', message='spawning process', cwd='/work/two')
        self.append(run='unrelated', message='spawning process', cwd='/work/one')
        self.append(run='unrelated', level='ERROR', message='Failed to drain Session', cause='quota')
        self.assertEqual(self.log.poll(), [])
        self.assertIsNone(self.log.server_run)

    async def test_runtime_notice_and_root_once_with_preset(self):
        runtime = SimpleNamespace(db=Mock(), post_message=AsyncMock())
        runtime.db.list_presets.return_value = []
        att = dict(id='a', conv_id='line', name='impl', adapter='opencode-v2',
                   command=[], preset='worker')
        callback = provider_error_callback(runtime, att)
        with patch('partyline.provider_errors.task', return_value={'root_id': 'root'}), \
                patch('partyline.provider_errors.notify_root', new_callable=AsyncMock) as root:
            await callback('account suspended [details redacted]', True)
            await callback('account suspended [details redacted]', False)
            await callback('authentication failed [details redacted]', True)
        self.assertEqual(runtime.post_message.await_count, 2)
        root.assert_awaited_once()
        self.assertIn('preset worker', root.call_args.args[2])

    def test_rotation_truncation_partial_and_missing(self):
        self.bind()
        self.log.poll()
        self.path.rename(self.path.with_suffix('.old'))
        self.assertEqual(self.log.poll(), [])
        self.path.write_text('')
        self.append(level='ERROR', message='Failed to drain Session', cause='quota')
        self.assertTrue(self.log.poll()[0][1])
        self.path.write_text('')
        self.assertEqual(self.log.poll(), [])
        with self.path.open('a') as stream:
            stream.write('run=aa level=ERROR message="provider failed" cause="bad api key"')
        self.assertEqual(self.log.poll(), [])
        with self.path.open('a') as stream:
            stream.write('\n')
        self.assertIn('authentication', self.log.poll()[0][0])
        absent = ProviderLog(self.path.with_suffix('.missing'), 'claim', '/work/one')
        self.assertEqual(absent.poll(), [])

    def test_safe_classes_and_malformed_fields(self):
        for cause, word in [('unknown model private', 'unknown model'),
                            ('billing token=secret', 'billing'),
                            ('arbitrary private details', 'provider request'), ('', 'provider')]:
            self.assertIn(word, safe_cause(cause))
        self.assertEqual(fields('cause="bad\\q"'), {})

    async def test_start_snapshots_before_pty_spawn(self):
        adapter = PartylineAdapter(dict(id='a', name='impl', command=[], cwd='/work'),
                                   AsyncMock(), AsyncMock())
        with patch.object(adapter, '_resolve_path', return_value=self.path.parent) as resolve, \
                patch('partyline.adapters.Adapter.start', new_callable=AsyncMock) as start:
            await adapter.start()
        resolve.assert_called_once_with('log')
        start.assert_awaited_once()
        self.assertEqual(adapter._provider_log.offset, self.path.stat().st_size)
