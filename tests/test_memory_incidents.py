import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline.auth_guard import Principal
from partyline.db import Db
from partyline.memory_contracts import ProcessExit
from partyline.memory_routes import register_memory_routes
from partyline.process_incidents import exit_callback, last_incident, record_exit
from partyline.runtime import ChatRuntime


class IncidentTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Db(f'{self.tmp.name}/test.db')
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.runtime.broadcast = AsyncMock()
        for line, parent in [('root', None), ('child', 'root'), ('sibling', 'root')]:
            self.db.create_conversation(line, line)
            self.db._exec('UPDATE conversations SET parent_id=? WHERE id=?', (parent, line))
        self.worker = self.attach('worker', 'child')
        self.captain = self.attach('captain', 'child', lead=True)
        self.parent = self.attach('parent', 'root', lead=True)
        self.sibling = self.attach('sibling', 'sibling', lead=True)
        self.evidence = ProcessExit(code=-15, reason='oom', limit_bytes=4 * 1024**3,
                                    peak_bytes=4 * 1024**3, result='oom-kill')

    def attach(self, ident, line, *, lead=False):
        att = self.db.add_attachment(ident, line, ident, 'raw', ['cat'], self.tmp.name, f'{ident}-owner')
        self.db._exec('UPDATE attachments SET is_lead=?,status=\'running\' WHERE id=?', (lead, ident))
        att = self.db.get_attachment(ident)
        self.runtime.live[ident] = SimpleNamespace(att=att, deliver=AsyncMock(return_value=True))
        return att

    async def exit(self, att):
        await self.runtime.status_callback(att['id'], att['conv_id'], att['runtime_owner'])('exited')
        await exit_callback(self.runtime, att)(self.evidence)

    async def test_confirmed_oom_is_durable_and_wakes_only_own_captain_once(self):
        # Sol's repro: a 6 GiB budget killed at its 9 GiB backstop, 8 GiB ceiling.
        self.db._exec("UPDATE attachments SET memory_limit='6G' WHERE id='worker'")
        self.evidence = ProcessExit(code=-15, reason='oom', limit_bytes=9 * 1024**3,
                                    peak_bytes=9 * 1024**3, result='oom-kill')
        with patch("partyline.process_incidents.memory_ceiling", return_value=8 * 1024**3):
            await self.exit(self.worker)
            await record_exit(self.runtime, self.worker, self.evidence)
        incident = last_incident(self.db, 'worker')
        self.assertEqual(incident['reason'], 'oom')
        detail = self.db.list_messages('child')[-1]['body']
        self.assertIn(f"Incident {incident['id']}", detail)
        self.assertIn('/api/attachments/worker/memory-requests', detail)
        self.assertIn('recorded peak 9.0 GiB at the 9.0 GiB emergency backstop (budget 6.0 GiB)', detail)
        self.assertIn('"requested_limit":"8G"', detail)
        self.assertEqual(incident['code'], -15)
        self.assertEqual(self.db.get_attachment('worker')['status'], 'exited')
        messages = self.db.list_messages('child')
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[-1]['audience_attachment_id'], 'captain')
        self.assertEqual(messages[-1]['source_attachment_id'], 'worker')
        self.assertIn('Do not blindly restart', messages[-1]['body'])
        self.assertIn('{"limit":"8G"}', messages[-1]['body'])
        self.runtime.live['captain'].deliver.assert_awaited_once()
        self.runtime.live['parent'].deliver.assert_not_awaited()
        self.runtime.live['sibling'].deliver.assert_not_awaited()
        reopened = Db(self.db.path)
        try:
            self.assertEqual(last_incident(reopened, 'worker')['id'], incident['id'])
        finally:
            reopened.close()

    async def test_dead_captain_escalates_to_parent_with_source_identity(self):
        await self.exit(self.captain)
        messages = self.db.list_messages('root')
        self.assertEqual(messages[-1]['audience_attachment_id'], 'parent')
        self.assertEqual(messages[-1]['source_conv_id'], 'child')
        self.runtime.live['parent'].deliver.assert_awaited_once()

    async def test_no_headroom_advice_omits_memory_update_examples(self):
        self.db._exec("UPDATE attachments SET memory_limit='8G' WHERE id='worker'")
        self.evidence = ProcessExit(code=-9, reason='oom', limit_bytes=12 * 1024**3,
                                    result='oom-kill')
        with patch('partyline.process_incidents.memory_ceiling', return_value=8 * 1024**3):
            await self.exit(self.worker)
        messages = self.db.list_messages('child')
        for message in messages:
            self.assertIn('No larger budget fits under the host ceiling.', message['body'])
            self.assertNotIn('a larger size', message['body'])
            self.assertNotIn('"limit":', message['body'])
            self.assertNotIn('/memory-requests', message['body'])
        self.assertIn("Reduce the workload's memory use", messages[-1]['body'])
        self.assertIn('Do not blindly restart', messages[-1]['body'])
        self.runtime.live['captain'].deliver.assert_awaited_once()

    async def test_unavailable_captain_is_skipped_and_no_captains_is_still_durable(self):
        self.runtime.live.pop('captain')
        await self.exit(self.worker)
        self.runtime.live['parent'].deliver.assert_awaited_once()
        another = self.attach('another', 'child')
        self.runtime.live.pop('parent')
        await self.exit(another)
        self.assertEqual(last_incident(self.db, 'another')['reason'], 'oom')
        self.assertEqual(len(self.db.list_messages('root')), 1)

    async def test_stale_activation_cannot_report_on_a_replacement(self):
        self.db._exec('UPDATE attachments SET runtime_owner=? WHERE id=?', ('new', 'worker'))
        await record_exit(self.runtime, self.worker, self.evidence)
        self.assertIsNone(last_incident(self.db, 'worker'))
        self.assertFalse(self.db.list_messages('child'))
        self.db._exec('DELETE FROM attachments WHERE id=?', ('worker',))
        await record_exit(self.runtime, self.worker, self.evidence)
        self.assertFalse(self.db.list_messages('child'))

    async def test_normal_exit_is_quiet_and_failure_without_evidence_stays_unknown(self):
        self.evidence = ProcessExit(code=0, limit_bytes=1024)
        await self.exit(self.worker)
        self.assertIsNone(last_incident(self.db, 'worker'))
        self.runtime.live['captain'].deliver.assert_not_awaited()
        other = self.attach('other', 'child')
        self.evidence = ProcessExit(code=-9, limit_bytes=1024)
        await self.exit(other)
        self.assertEqual(last_incident(self.db, 'other')['reason'], 'exit')
        self.assertNotIn('confirmed out-of-memory', self.db.list_messages('child')[-1]['body'])

    async def test_deleted_attachment_removes_private_diagnostics(self):
        await self.exit(self.worker)
        self.db._exec('DELETE FROM attachments WHERE id=?', ('worker',))
        self.assertIsNone(last_incident(self.db, 'worker'))


class MemoryRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Db(f'{self.tmp.name}/test.db')
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.runtime.broadcast = AsyncMock()
        for line in ('line', 'unrelated'):
            self.db.create_conversation(line, line)
        self.att = self.db.add_attachment('worker', 'line', 'worker', 'raw', ['cat'], self.tmp.name, 'owner')
        self.db.set_attachment_status('worker', 'exited', 'owner')
        self.actor = Principal(kind='user', name='operator', user_id=1)
        app = FastAPI()
        @app.middleware('http')
        async def principal(request, call_next):
            request.state.principal = self.actor
            return await call_next(request)
        register_memory_routes(app, self.runtime)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.path = '/api/attachments/worker/memory'
        self.limit_patch = patch('partyline.memory_routes.host_memory_bytes', return_value=16 * 1024**3)
        self.limit_patch.start()
        self.addCleanup(self.limit_patch.stop)
        self.env_patch = patch.dict('os.environ', {'PARTYLINE_PROCESS_MEMORY_LIMIT': '4G',
                                                 'PARTYLINE_MAX_PROCESS_MEMORY_LIMIT': '8G'})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_inspect_change_reset_and_audit_memory_limit(self):
        self.assertEqual(self.client.get(self.path).json()['effective_limit'], '4G')
        response = self.client.put(self.path, json={'limit': '6G'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['effective_limit'], '6G')
        self.assertEqual(self.db.get_attachment('worker')['memory_limit'], '6G')
        self.assertIn('next activation', self.db.list_messages('line')[-1]['body'])
        self.assertEqual(self.client.put(self.path, json={'limit': None}).json()['effective_limit'], '4G')
        evidence = ProcessExit(code=-15, reason='oom', limit_bytes=1024)
        asyncio.run(record_exit(self.runtime, self.att, evidence))
        self.assertEqual(self.client.get(self.path).json()['last_incident']['reason'], 'oom')

    def test_only_authorized_captain_can_adjust_another_process(self):
        self.actor = Principal(kind='machine', name='worker', conv_id='line', attachment_id='worker')
        self.assertEqual(self.client.get(self.path).status_code, 200)
        self.assertEqual(self.client.put(self.path, json={'limit': '6G'}).status_code, 403)
        self.actor = Principal(kind='machine', name='captain', conv_id='line',
                               attachment_id='captain', is_lead=True)
        self.assertEqual(self.client.put(self.path, json={'limit': '6G'}).status_code, 200)
        self.actor = Principal(kind='machine', name='worker', conv_id='line',
                               attachment_id='worker', is_lead=True)
        self.assertEqual(self.client.put(self.path, json={'limit': '6G'}).status_code, 403)
        self.actor = Principal(kind='machine', name='outsider', conv_id='unrelated', is_lead=True)
        self.assertEqual(self.client.get(self.path).status_code, 403)
        self.assertEqual(self.client.put(self.path, json={'limit': '6G'}).status_code, 403)

    def test_live_invalid_and_excessive_limits_are_refused(self):
        for limit in ('max', '0G', '-1G', '9', '1T'):
            self.assertEqual(self.client.put(self.path, json={'limit': limit}).status_code, 422)
        self.assertEqual(self.client.put(self.path, json={'limit': '9G'}).status_code, 400)
        with patch('partyline.memory_routes.host_memory_bytes', return_value=4 * 1024**3):
            self.assertEqual(self.client.put(self.path, json={'limit': '4G'}).status_code, 400)
        self.db.set_attachment_status('worker', 'running', 'owner')
        self.assertEqual(self.client.put(self.path, json={'limit': '6G'}).status_code, 409)
        self.db.set_attachment_status('worker', 'exited', 'owner')
        self.runtime.live['worker'] = object()
        self.assertEqual(self.client.put(self.path, json={'limit': '6G'}).status_code, 409)
        self.assertEqual(self.client.get('/api/attachments/missing/memory').status_code, 404)

    def test_fresh_attachment_keeps_approved_limit(self):
        from partyline.attachment_lifecycle import FreshAttachmentRequest, create_fresh_record
        self.client.put(self.path, json={'limit': '6G'})
        att = self.db.get_attachment('worker')
        fresh = asyncio.run(create_fresh_record(self.db, att, FreshAttachmentRequest()))
        self.assertEqual(fresh['memory_limit'], '6G')

    def test_removal_while_waiting_for_settings_lock_is_not_a_server_error(self):
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def removed():
            self.db._exec('DELETE FROM attachments WHERE id=?', ('worker',))
            yield
        with patch.object(self.db, '_runtime_serialized_async', removed):
            self.assertEqual(self.client.put(self.path, json={'limit': '6G'}).status_code, 404)
