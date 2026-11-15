"""File input dispatch and staging use only the approved CDP session."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from partyline_helper.cdp_files import FINISH, START, filename, set_files
from partyline_helper.cdp_transport import CDPError
from tests.cdp_fakes import Fixture


class FileInput(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        tree = await self.f.read()
        self.ident = tree['elements'][2]['id']
        self.page = await self.f.chrome.page(self.f.access)
        self.page.quiet.wait = AsyncMock(return_value='quiet')
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    async def test_single_and_multiple_files_read_back_and_cleanup(self):
        self.f.socket.states[3].update(tag='INPUT', type='file')
        original = self.f.socket.response
        staged, cleanup = [], []
        def response(message):
            if message['method'] == 'Runtime.callFunctionOn':
                recipe = message['params']['functionDeclaration']
                if recipe == START:
                    return {'result': {'value': {'multiple': True}}}
                if recipe == FINISH:
                    dispatch = [m for m in self.f.socket.calls if m['method'] == 'DOM.setFileInputFiles'][-1]
                    names = ['a.txt', 'b.txt'][:len(dispatch['params']['files'])]
                    return {'result': {'value': {'files': names, 'count': len(names)}}}
            if message['method'] == 'DOM.setFileInputFiles':
                names = ['a.txt', 'b.txt'][:len(message['params']['files'])]
                self.f.socket.states[3].update(files=names, file_count=len(names))
            return original(message)
        self.f.socket.response = response
        def download(session, page, ticket, files, directory):
            paths = []
            for i, _file in enumerate(files):
                path = directory / f'{i}.txt'
                path.write_bytes(b'x')
                paths.append(str(path))
            staged.append(directory)
            return paths
        messages = [dict(id='a', name='a.txt', bytes=1), dict(id='b', name='b.txt', bytes=1)]
        with patch('partyline_helper.cdp_files.config_path', return_value=Path(self.temp.name) / 'config'), \
             patch('partyline_helper.cdp_files.download', side_effect=download), \
             patch('partyline_helper.cdp_files.schedule_cleanup',
                   side_effect=lambda path, *args: cleanup.append(path)):
            for count in (1, 2):
                result = await self.f.chrome.action(
                    self.f.access, dict(action='set_files', element_id=self.ident,
                                        files=messages[:count], file_ticket='ticket'))
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(result['files'], ['a.txt', 'b.txt'][:count])
                entry = self.f.session.tools.audit.append.call_args.args[-1]
                self.assertIn('\"operation\":\"set_files\"', entry)
                self.assertIn('\"total_bytes\":', entry)
                dispatch = [m for m in self.f.socket.calls if m['method'] == 'DOM.setFileInputFiles'][-1]
                self.assertEqual(len(dispatch['params']['files']), count)
                self.assertFalse(any(m['method'] in ('DOM.focus', 'DOM.scrollIntoViewIfNeeded')
                                     for m in self.f.socket.calls))
            import shutil
            for directory in set(cleanup):
                shutil.rmtree(directory)
        self.assertTrue(all(not item.exists() for item in staged))

    async def test_wrong_type_multiple_and_revoke_refused(self):
        files = [dict(id='a', name='a', bytes=1), dict(id='b', name='b', bytes=1)]
        for state, expected in (({'error': 'element is not a file input'}, 'file input'),
                                ({'multiple': False}, 'multiple')):
            self.page.function = AsyncMock(return_value=state)
            with self.assertRaisesRegex(CDPError, expected):
                await set_files(self.page, {'files': files}, 3)
        self.page.function = AsyncMock(return_value={'multiple': True})
        def revoke(session, page, ticket, files, directory):
            self.f.access.gate.invalidate()
            return [str(directory / 'x')]
        with patch('partyline_helper.cdp_files.config_path', return_value=Path(self.temp.name) / 'config'), \
             patch('partyline_helper.cdp_files.download', side_effect=revoke):
            with self.assertRaises(CDPError):
                await set_files(self.page, {'files': files, 'file_ticket': 'ticket'}, 3)
        self.assertFalse(any(m['method'] == 'DOM.setFileInputFiles' for m in self.f.socket.calls))
        self.assertEqual(list((Path(self.temp.name) / 'file-input').iterdir()), [])

    async def test_page_changed_during_download_refused(self):
        self.page.function = AsyncMock(return_value={'multiple': True})
        self.f.chrome.page = AsyncMock(return_value=None)
        files = [dict(id='a', name='a', bytes=1)]
        with patch('partyline_helper.cdp_files.config_path', return_value=Path(self.temp.name) / 'config'), \
             patch('partyline_helper.cdp_files.download', return_value=['staged']):
            with self.assertRaisesRegex(CDPError, 'page changed'):
                await set_files(self.page, {'files': files, 'file_ticket': 'ticket'}, 3)
        self.assertFalse(any(m['method'] == 'DOM.setFileInputFiles' for m in self.f.socket.calls))
        self.assertEqual(list((Path(self.temp.name) / 'file-input').iterdir()), [])

    async def test_uia_never_receives_file_action(self):
        self.f.chrome.sources[self.f.access] = 'uia'
        result = await self.f.chrome.action(self.f.access, dict(action='set_files', element_id=self.ident))
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Open dialog', result['error'])


class Names(TestCase):
    def test_filename_is_a_safe_basename(self):
        self.assertEqual(filename(r'C:\\secret\\name.txt'), 'name.txt')
        self.assertEqual(filename('CON'), 'file')
        self.assertEqual(filename('../a?.txt'), 'a_.txt')
        long_name = filename('😀' * 150 + '.txt')
        self.assertLessEqual(len(long_name.encode()), 200)
        self.assertTrue(long_name.endswith('.txt'))


from fastapi import HTTPException
from unittest.mock import patch as mock_patch
from partyline.auth_guard import Principal
from partyline.media_files import MAX_FILE_BYTES, prepared_file
from partyline.screen_file_input import MAX_TOTAL, audit_files, resolve_files, ticket
from tests.window_grant_fixtures import WindowGrantFixture


class ServerFiles(WindowGrantFixture, IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.db._exec('UPDATE conversations SET parent_id=? WHERE id=?', ('paired', 'alpha'))
        self.principal = Principal(kind='machine', name='a', conv_id='alpha', attachment_id='a')

    def put(self, line, content=b'abc'):
        message = self.db.add_message(line, 'owner', 'human', '')
        file = prepared_file((content, 'name.txt', 'text/plain'))
        return self.store.store(line, message['id'], [file], None, None)[0].id

    async def test_visibility_caps_ticket_and_audit(self):
        own, ancestor, outside = self.put('alpha'), self.put('paired'), self.put('beta')
        fixed_id = 'abc00000-0000-4000-8000-000000000000'
        self.db._exec('UPDATE images SET id=? WHERE id=?', (fixed_id, own))
        own = fixed_id
        files, total = resolve_files(self.hub, self.principal, [own, ancestor])
        self.assertEqual(total, 6)
        for ident in (outside, 'missing'):
            with self.assertRaises(HTTPException) as failure:
                resolve_files(self.hub, self.principal, [ident])
            self.assertEqual(failure.exception.status_code, 404)
        with mock_patch('partyline.screen_file_input.MAX_FILE_BYTES', 2):
            with self.assertRaises(HTTPException) as failure:
                resolve_files(self.hub, self.principal, [own])
            self.assertEqual(failure.exception.status_code, 413)
        with mock_patch('partyline.screen_file_input.MAX_TOTAL', 5):
            with self.assertRaises(HTTPException) as failure:
                resolve_files(self.hub, self.principal, [own, ancestor])
            self.assertEqual(failure.exception.status_code, 413)
        await self.grant('a')
        grant = {'id': 'g1', 'conv_id': 'alpha', 'device_id': self.device['id']}
        audit_files(self.hub, self.principal, grant, [own, ancestor], total)
        entry = self.db._exec('SELECT entry FROM screen_control_audit ORDER BY id DESC').fetchone()['entry']
        self.assertEqual(json.loads(entry), {
            'grant': 'g1', 'line': 'alpha', 'process': 'a', 'operation': 'set_files',
            'file_count': 2, 'total_bytes': 6, 'media_ids': [own, ancestor],
        })
        device_token = 'device-secret'
        self.db._exec('UPDATE screen_devices SET token_hash=? WHERE id=?',
                      (self.hub.digest(device_token), self.device['id']))
        with ticket(self.hub, self.principal, grant, files) as key:
            url = f'/api/screen/file-input/{key}/0'
            self.assertEqual((await self.client.get(url)).status_code, 404)
            self.assertEqual((await self.client.get(url, headers=self.machine('a'))).status_code, 404)
            result = await self.client.get(url, headers={'Authorization': 'Bearer ' + device_token})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.content, b'abc')
        self.assertEqual((await self.client.get(url, headers={'Authorization': 'Bearer ' + device_token}))
                         .status_code, 404)

    async def test_default_size_boundaries(self):
        large, tiny = self.put('alpha'), self.put('alpha', b'x')
        path, _, _ = self.store.file_for(large, 'original')
        with path.open('wb') as stream:
            stream.truncate(MAX_FILE_BYTES)
        self.assertEqual(resolve_files(self.hub, self.principal, [large])[1], MAX_FILE_BYTES)
        self.assertEqual(resolve_files(self.hub, self.principal, [large, large])[1], MAX_TOTAL)
        with self.assertRaises(HTTPException) as total:
            resolve_files(self.hub, self.principal, [large, large, tiny])
        self.assertEqual(total.exception.status_code, 413)
        with path.open('wb') as stream:
            stream.truncate(MAX_FILE_BYTES + 1)
        with self.assertRaises(HTTPException) as single:
            resolve_files(self.hub, self.principal, [large])
        self.assertEqual(single.exception.status_code, 413)

    async def test_action_sends_capability_not_paths_and_reports_files(self):
        ident = self.put('alpha')
        await self.grant('a')
        self.device['chrome_dom'] = 2
        await self.read('a')
        element = next(iter(self.hub.elements.snapshots['g1'].nodes))
        self.db._exec('UPDATE screen_devices SET token_hash=? WHERE id=?',
                      (self.hub.digest('device-secret'), self.device['id']))
        old_receive = self.receive
        async def receive(message):
            if message['type'] != 'window_element_action':
                return await old_receive(message)
            self.assertEqual(message['files'][0]['id'], ident)
            self.assertNotIn('path', message['files'][0])
            url = f"/api/screen/file-input/{message['file_ticket']}/0"
            reply = await self.client.get(url, headers={'Authorization': 'Bearer device-secret'})
            self.assertEqual(reply.content, b'abc')
            self.hub.elements.receive(self.device, dict(request_id=message['request_id'], status='completed',
                                                       source='cdp', files=['name.txt'], count=1,
                                                       settle='quiet', settled_event_counter=0))
        self.device['socket'].send_json = receive
        response = await self.client.post('/api/conversations/alpha/screen-control/element-action',
            headers=self.machine('a'), json=dict(action='set_files', element_id=element,
                                                files=[ident], then={}))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['after']['files'], ['name.txt'])
        self.assertEqual(response.json()['after']['file_count'], 1)
        self.assertFalse(self.hub.file_tickets)
