"""Local file input paths are resolved, bounded and audited without staging."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from partyline_helper.cdp_files import START, set_files
from partyline_helper.cdp_local_files import prepare
from partyline_helper.cdp_transport import CDPError


class LocalPaths(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'helper'
        self.data.mkdir()
        self.config = self.data / 'helper.json'
        self.config.write_text('private token')
        self.public = self.root / 'public.txt'
        self.public.write_bytes(b'hello')
        self.limits = {'file': 5, 'total': 10}
        config = patch('partyline_helper.cdp_local_files.config_path', return_value=self.config)
        config.start()
        self.addCleanup(config.stop)

    def test_absolute_regular_files_and_symlinks(self):
        link = self.root / 'link.txt'
        link.symlink_to(self.public)
        result, total = prepare([str(link)], [], self.limits)
        self.assertEqual(result, [{'path': str(self.public), 'bytes': 5}])
        self.assertEqual(total, 5)
        for value in ('relative.txt', str(self.root / 'missing'), str(self.root)):
            with self.subTest(value=value), self.assertRaises(CDPError):
                prepare([value], [], self.limits)
        link.unlink()
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(CDPError):
            prepare([str(link)], [], self.limits)

    def test_non_regular_file_is_refused_without_opening_it(self):
        if not hasattr(os, 'mkfifo'):
            self.skipTest('named pipes are unavailable')
        pipe = self.root / 'pipe'
        os.mkfifo(pipe)
        with self.assertRaisesRegex(CDPError, 'regular file'):
            prepare([str(pipe)], [], self.limits)

    def test_helper_data_and_symlink_are_denied(self):
        alias = self.root / 'shortcut'
        alias.symlink_to(self.data, target_is_directory=True)
        for value in (self.config, alias / 'helper.json'):
            with self.subTest(value=value), self.assertRaisesRegex(CDPError, 'helper data'):
                prepare([str(value)], [], self.limits)

    def test_default_limits_with_sparse_files(self):
        maximum = 100 * 1024 * 1024
        with self.public.open('wb') as stream:
            stream.truncate(maximum)
        limits = {'file': maximum, 'total': 2 * maximum}
        self.assertEqual(prepare([str(self.public)], [{'bytes': maximum}], limits)[1], 2 * maximum)
        with self.assertRaisesRegex(CDPError, 'per-call'):
            prepare([str(self.public)], [{'bytes': maximum + 1}], limits)
        with self.public.open('wb') as stream:
            stream.truncate(maximum + 1)
        with self.assertRaisesRegex(CDPError, 'per-file'):
            prepare([str(self.public)], [], limits)

    def test_per_file_and_combined_caps(self):
        media = [{'bytes': 5}]
        self.assertEqual(prepare([str(self.public)], media, self.limits)[1], 10)
        with self.assertRaisesRegex(CDPError, 'per-call'):
            prepare([str(self.public)], [{'bytes': 6}], self.limits)
        with self.assertRaisesRegex(CDPError, 'per-file'):
            prepare([str(self.public)], [], {'file': 4, 'total': 10})


class LocalDispatch(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.data = root / 'helper'
        self.data.mkdir()
        self.file = root / 'local.txt'
        self.file.write_bytes(b'local')
        self.session = SimpleNamespace(window_grant_id='g', tools=SimpleNamespace(audit=Mock()))
        self.page = SimpleNamespace(access=SimpleNamespace(session=self.session), guard=Mock(),
                                    function=AsyncMock(), call=AsyncMock())
        self.session.chrome = SimpleNamespace(page=AsyncMock(return_value=self.page))
        self.page.function.side_effect = lambda backend, recipe, *args: (
            {'multiple': True} if recipe == START else {'files': ['local.txt'], 'count': 1})
        self.message = {'paths': [str(self.file)], 'files': [], 'file_ticket': 'ticket',
                        'file_limits': {'file': 100, 'total': 200}, 'line_id': 'line', 'agent': 'agent'}
        for target in ('partyline_helper.cdp_local_files.config_path',
                       'partyline_helper.cdp_files.config_path'):
            patcher = patch(target, return_value=self.data / 'helper.json')
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_local_path_is_direct_and_audited(self):
        with patch('partyline_helper.cdp_local_files.audit_remote') as remote:
            result = await set_files(self.page, self.message, 42)
        self.assertEqual(result['count'], 1)
        self.page.call.assert_awaited_once_with('DOM.setFileInputFiles',
                                                {'files': [str(self.file)], 'backendNodeId': 42})
        self.assertFalse((self.data / 'file-input').exists())
        path_data = [{'path': str(self.file), 'bytes': 5}]
        self.assertEqual(remote.call_args.args[-1], path_data)
        info = json.loads(self.session.tools.audit.append.call_args.args[-1])
        self.assertEqual(info['paths'], path_data)
        self.assertEqual(info['total_bytes'], 5)

    async def test_local_only_call_cleans_expired_media_staging(self):
        stale = self.data / 'file-input' / 'old'
        stale.mkdir(parents=True)
        (stale / 'media').write_bytes(b'old')
        os.utime(stale, (1, 1))
        with patch('partyline_helper.cdp_files.time.time', return_value=10000), \
             patch('partyline_helper.cdp_local_files.audit_remote'):
            await set_files(self.page, self.message, 42)
        self.assertFalse(stale.exists())

    async def test_audit_failure_stops_before_cdp(self):
        with patch('partyline_helper.cdp_local_files.audit_remote', side_effect=CDPError('audit failed')):
            with self.assertRaisesRegex(CDPError, 'audit failed'):
                await set_files(self.page, self.message, 42)
        self.page.call.assert_not_awaited()
        self.assertFalse((self.data / 'file-input').exists())

    async def test_symlink_retargeted_during_page_check_is_refused(self):
        secret = self.data / 'helper.json'
        secret.write_text('secret')
        link = self.file.parent / 'alias'
        link.symlink_to(self.file)
        self.message['paths'] = [str(link)]
        async def remap(access):
            link.unlink()
            link.symlink_to(secret)
            return self.page
        self.session.chrome.page.side_effect = remap
        with patch('partyline_helper.cdp_local_files.audit_remote'):
            with self.assertRaisesRegex(CDPError, 'helper data'):
                await set_files(self.page, self.message, 42)
        self.page.call.assert_not_awaited()

    async def test_mixed_files_stage_only_media(self):
        media = [{'id': 'media', 'name': 'media.txt', 'bytes': 3}]
        self.message['files'] = media
        staged = []
        def download(session, page, ticket, files, directory):
            path = directory / 'media.txt'
            path.write_bytes(b'abc')
            staged.append(directory)
            return [str(path)]
        with patch('partyline_helper.cdp_local_files.audit_remote') as remote, \
             patch('partyline_helper.cdp_files.download', side_effect=download), \
             patch('partyline_helper.cdp_files.schedule_cleanup'):
            await set_files(self.page, self.message, 42)
        actual = self.page.call.await_args.args[1]['files']
        self.assertEqual(actual, [str(staged[0] / 'media.txt'), str(self.file)])
        self.assertEqual(remote.call_args.args[-1], [{'path': str(self.file), 'bytes': 5}])
        info = json.loads(self.session.tools.audit.append.call_args.args[-1])
        self.assertEqual(info['media_ids'], ['media'])
        self.assertEqual(info['total_bytes'], 8)


from partyline.screen_file_input import ticket
from tests.window_grant_fixtures import WindowGrantFixture


class LocalServer(WindowGrantFixture, IsolatedAsyncioTestCase):
    async def test_server_audits_helper_paths_and_sizes_before_action(self):
        await self.grant('a')
        self.device['chrome_dom'] = 3
        await self.read('a')
        element = next(iter(self.hub.elements.snapshots['g1'].nodes))
        self.db._exec('UPDATE screen_devices SET token_hash=? WHERE id=?',
                      (self.hub.digest('device-secret'), self.device['id']))
        previous = self.receive
        local = [{'path': r'C:\Documents\report.txt', 'bytes': 12}]
        async def receive(message):
            if message['type'] != 'window_element_action':
                return await previous(message)
            self.assertEqual(message['paths'], [local[0]['path']])
            self.assertEqual(message['file_limits'], {'file': 100 * 1024 * 1024, 'total': 200 * 1024 * 1024})
            url = f"/api/screen/file-input/{message['file_ticket']}/audit"
            self.assertEqual((await self.client.post(url, json={'paths': local})).status_code, 404)
            headers = {'Authorization': 'Bearer device-secret'}
            reply = await self.client.post(url, json={'paths': local}, headers=headers)
            self.assertEqual(reply.status_code, 200, reply.text)
            audit = self.db._exec('SELECT entry FROM screen_control_audit ORDER BY id DESC').fetchone()
            entry = json.loads(audit['entry'])
            self.assertEqual(entry['paths'], local)
            self.assertEqual(entry['total_bytes'], 12)
            self.assertEqual(entry['file_count'], 1)
            self.hub.elements.receive(self.device, dict(request_id=message['request_id'],
                                                       status='completed', source='cdp',
                                                       files=['report.txt'], count=1))
        self.device['socket'].send_json = receive
        response = await self.client.post('/api/conversations/alpha/screen-control/element-action',
            headers=self.machine('a'), json=dict(action='set_files', element_id=element,
                                                paths=[local[0]['path']]))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['files'], ['report.txt'])
        self.assertFalse(self.hub.file_tickets)

    async def test_total_file_count_is_validated(self):
        from partyline.screen_element_actions import ElementAction
        for args in ({}, {'files': ['a'] * 6, 'paths': ['/b'] * 5}):
            with self.assertRaises(ValueError):
                ElementAction(action='set_files', element_id='x', **args).parameters()
        with ticket(self.hub, None, {'id': 'grant'}, [], 1) as key:
            url = f'/api/screen/file-input/{key}/audit'
            result = await self.client.post(url, json={'paths': [{'path': '/x', 'bytes': 1}]})
            self.assertEqual(result.status_code, 404)
