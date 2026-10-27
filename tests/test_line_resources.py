"""Exclusive line resources use scratch databases and synthetic task attachments."""

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from partyline import line_resources as leases
from partyline.db import Db
from partyline.line_resource_routes import maintain, register_line_resource_routes, run
from partyline.mcp import tools_resources
from partyline.memory_contracts import ProcessExit
from partyline.process_incidents import record_exit
from tests.orchestrator_fixture import TaskFixture


class LineResourcesTest(TaskFixture):
    async def asyncSetUp(self):
        import os
        environment = patch.dict(os.environ, {'PARTYLINE_RESOURCE_PROBES': '{"gpu":null}'})
        environment.start()
        self.addCleanup(environment.stop)
        register_line_resource_routes(self.app, self.runtime)
        await self.create()
        self.first = self.worker
        self.db._exec("UPDATE task_reviews SET reviewer_id='inspect' WHERE conv_id=?", (self.conv_id,))
        self.db.add_attachment('inspect', self.conv_id, 'inspector', 'fake', ['fake'], self.repo, 'owner')
        self.db.set_attachment_status('inspect', 'running', 'owner')
        self.second = self.principal('inspect')
        self.actor = self.captain
        self.manage('declare', 'gpu')

    def manage(self, op, name=None):
        return self.client.post('/api/conversations/root/resources',
                                json={'operation': op, **({'name': name} if name else {})})

    def acquire(self, actor=None, name='gpu', **body):
        self.actor = actor or self.first
        return self.client.post(f'/api/task/resources/{name}/acquire', json=body)

    def release(self, actor=None, name='gpu'):
        self.actor = actor or self.first
        return self.client.post(f'/api/task/resources/{name}/release')

    def claims(self):
        return leases.report(self.db, 'root')['resources'][0]

    async def test_fifo_and_one_private_notice(self):
        self.assertEqual(self.acquire(note='training').json()['status'], 'held')
        self.assertEqual(self.acquire(note='ignored').json()['holder']['note'], 'training')
        queued = self.acquire(self.second).json()
        self.assertEqual((queued['status'], queued['position']), ('queued', 1))
        self.assertEqual(queued['holder']['attachment_id'], self.first.attachment_id)
        self.assertEqual(self.acquire(self.second).json()['position'], 1)
        self.assertEqual(len(self.claims()['queue']), 1)
        self.release()
        self.assertEqual(self.claims()['holder']['attachment_id'], 'inspect')
        await maintain(self.runtime)
        notices = [m for m in self.db.list_messages(self.conv_id) if 'you now hold gpu' in m['body']]
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['audience_attachment_id'], 'inspect')
        self.assertEqual(self.acquire(self.second).json()['status'], 'held')
        self.release(self.second)
        self.assertIsNone(self.claims()['holder'])

    async def test_order_cancel_and_stale_waiter(self):
        self.acquire()
        self.acquire(self.second)
        for ident in ('third', 'fourth'):
            self.db.add_attachment(ident, 'root', ident, 'fake', ['fake'], self.repo, 'owner')
            self.db.set_attachment_status(ident, 'running', 'owner')
            leases.acquire(self.db, 'root', 'gpu', ident)
        self.release(self.second)
        self.db._exec("DELETE FROM attachments WHERE id='third'")
        self.release()
        self.assertEqual(self.claims()['holder']['attachment_id'], 'fourth')

    async def test_permissions_bounds_and_declarations(self):
        self.assertEqual(self.manage('declare', 'gpu').status_code, 200)
        self.assertEqual(len(leases.report(self.db, 'root')['resources']), 1)
        self.acquire()
        self.assertEqual(self.manage('declare', 'other').status_code, 403)
        self.assertEqual(self.acquire(self.captain).status_code, 403)
        self.assertEqual(self.acquire(self.human).status_code, 403)
        self.assertEqual(self.acquire(note='x' * 501).status_code, 422)
        self.assertEqual(self.acquire(name='missing').status_code, 404)
        self.actor = self.captain
        self.assertEqual(self.manage('remove', 'gpu').status_code, 409)
        self.assertEqual(self.manage('declare', 'bad name').status_code, 422)
        self.assertEqual(self.manage('declare').status_code, 422)
        self.assertEqual(self.client.post('/api/task/resources/gpu/acquire',
                                        json={'attachment_id': 'inspect'}).status_code, 422)
        self.release()
        self.actor = self.captain
        self.assertEqual(self.manage('remove', 'gpu').status_code, 200)
        self.assertEqual(self.manage('list').json(), {'resources': []})
        with self.assertRaises(HTTPException):
            leases.manage(self.db, 'root', 'invalid', 'gpu')
        with self.assertRaises(HTTPException):
            leases.acquire(self.db, 'root', 'gpu', 'inspect', 'x' * 501)
        with self.assertRaises(HTTPException):
            leases.resolve(self.db, 'root', 'bad name')

    async def test_queue_bound(self):
        self.acquire()
        for i in range(leases.MAX_QUEUE):
            ident = f'q{i}'
            self.db.add_attachment(ident, 'root', ident, 'fake', ['fake'], self.repo, 'owner')
            self.db.set_attachment_status(ident, 'running', 'owner')
            leases.acquire(self.db, 'root', 'gpu', ident)
        self.assertEqual(self.acquire(self.second).status_code, 409)

    async def test_detach_replacement_archive_and_missing_holder(self):
        for action in ('detach', 'replace', 'archive', 'delete'):
            with self.subTest(action=action):
                self.db._exec("UPDATE conversations SET archived_at=NULL WHERE id=?", (self.conv_id,))
                self.db._exec("UPDATE attachments SET status='running' WHERE id=?",
                              (self.first.attachment_id,))
                self.acquire()
                # A waiter on another child survives the holder's line archive.
                self.db.create_conversation('wait-' + action, 'Wait')
                ident = 'w-' + action
                self.db.add_attachment(ident, 'wait-' + action, ident, 'fake', ['fake'], self.repo, 'owner')
                self.db.set_attachment_status(ident, 'running', 'owner')
                leases.acquire(self.db, 'root', 'gpu', ident)
                if action == 'detach':
                    from partyline.line_process_routes import detach_attachment
                    await detach_attachment(self.runtime, self.first.attachment_id, survivors=False)
                elif action == 'replace':
                    self.db._exec('UPDATE attachments SET runtime_owner=? WHERE id=?',
                                  ('new', self.first.attachment_id))
                elif action == 'archive':
                    self.db._exec('UPDATE conversations SET archived_at=1 WHERE id=?', (self.conv_id,))
                else:
                    # Simulate a missed cleanup hook rather than relying on the delete trigger.
                    self.db._exec('DROP TRIGGER line_resource_attachment_delete')
                    self.db._exec('DELETE FROM attachments WHERE id=?', (self.first.attachment_id,))
                await maintain(self.runtime)
                self.assertEqual(self.claims()['holder']['attachment_id'], ident)
                leases.release(self.db, 'root', 'gpu', ident)

    async def test_exit_releases_and_skips_stopped_waiter(self):
        self.acquire()
        self.acquire(self.second)
        self.db.set_attachment_status('inspect', 'exited', 'owner')
        att = self.db.get_attachment(self.first.attachment_id)
        await record_exit(self.runtime, att, ProcessExit(code=0, reason='exit', limit_bytes=1024**3))
        self.assertIsNone(self.claims()['holder'])
        self.db.set_attachment_status('inspect', 'running', 'owner')
        self.acquire(self.second)
        att = self.db.get_attachment('inspect')
        await record_exit(self.runtime, att, ProcessExit(code=1, reason='exit', limit_bytes=1024**3))
        self.assertIsNone(self.claims()['holder'])

    async def test_schema_reopen_and_resource_line_removal(self):
        self.acquire()
        second_db = Db(self.db.path)
        try:
            self.assertEqual(leases.report(second_db, 'root'), leases.report(self.db, 'root'))
        finally:
            second_db.close()
        self.db._exec("DELETE FROM conversations WHERE id='root'")
        self.assertEqual(leases.report(self.db, 'root'), {'resources': []})
        self.assertEqual(self.db._exec('SELECT count(*) FROM line_resource_claims').fetchone()[0], 0)

    async def test_delivery_failure_retries_same_message_and_periodic_sweep(self):
        self.acquire()
        self.acquire(self.second)
        self.db.set_attachment_status(self.first.attachment_id, 'exited',
                                      self.db.get_attachment(self.first.attachment_id)['runtime_owner'])
        self.runtime.route_mentions.side_effect = RuntimeError('temporary')
        with self.assertRaises(RuntimeError):
            await maintain(self.runtime)
        self.runtime.route_mentions.side_effect = None
        await maintain(self.runtime)
        self.assertEqual(len([m for m in self.db.list_messages(self.conv_id)
                              if 'you now hold gpu' in m['body']]), 1)
        with patch('partyline.line_resource_routes.maintain', new=AsyncMock(side_effect=RuntimeError)), \
                patch('partyline.line_resource_routes.asyncio.sleep', new=AsyncMock(
                    side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await run(self.runtime)

    async def test_mcp_task_tools(self):
        from unittest.mock import Mock
        client = Mock()
        state = {'role': 'implementer'}
        self.assertEqual(len(tools_resources.tool_list(state)), 2)
        self.assertEqual(tools_resources.tool_list({'role': 'lead'}), [])
        tools_resources.call(client, 'acquire_resource', {'name': 'gpu'}, state)
        client.request.assert_called_with('POST', '/api/task/resources/gpu/acquire', {'note': ''})
        tools_resources.call(client, 'release_resource', {'name': 'gpu'}, {'role': 'reviewer'})
        client.request.assert_called_with('POST', '/api/task/resources/gpu/release', None)
        with self.assertRaises(ValueError):
            tools_resources.call(client, 'acquire_resource', {'name': 'gpu', 'note': 'x' * 501}, state)
        from partyline.mcp.client import ApiError
        with self.assertRaises(ApiError):
            tools_resources.call(client, 'acquire_resource', {'name': 'gpu'}, {'role': 'lead'})

    async def test_other_task_shares_parent_resource_and_unrelated_captain_cannot_manage(self):
        from partyline.orchestrator_service import create_task
        from partyline.orchestrator_contracts import TaskIn
        row = await create_task(self.runtime, self.captain, 'root', TaskIn(
            name='another', goal='Another job', implementer='builder', review='captain'))
        other = self.principal(row['implementer_id'])
        self.acquire()
        self.assertEqual(self.acquire(other).json()['status'], 'queued')
        self.release(self.second)  # Cannot release the implementer's lease.
        self.assertEqual(self.claims()['holder']['attachment_id'], self.first.attachment_id)
        self.release()
        self.assertEqual(self.claims()['holder']['attachment_id'], other.attachment_id)
        from partyline.process_overview import process_overview
        overview = process_overview(self.runtime, 'root')
        self.assertEqual(overview.lines[0].resources[0].holder.attachment_id, other.attachment_id)
        self.db.create_conversation('foreign', 'Foreign')
        self.db.add_attachment('rival', 'foreign', 'rival', 'fake', ['fake'], self.repo, 'owner')
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='rival'")
        self.actor = self.principal('rival')
        self.assertEqual(self.manage('declare', 'port-8000').status_code, 403)
        self.assertEqual(self.acquire(other, name='port-8000').status_code, 404)

    async def test_concurrent_connections_serialize_the_last_slot(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        other_db = Db(self.db.path)
        self.addCleanup(other_db.close)
        barrier = threading.Barrier(2)

        def take(db, ident):
            barrier.wait(timeout=5)
            return leases.acquire(db, 'root', 'gpu', ident)['status']

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(take, self.db, self.first.attachment_id)
            b = pool.submit(take, other_db, self.second.attachment_id)
            self.assertCountEqual([a.result(timeout=5), b.result(timeout=5)], ['held', 'queued'])

    async def test_fifo_multiple_waiters_and_retired_holder_line(self):
        self.acquire()
        self.acquire(self.second)
        for ident in ('third', 'fourth'):
            self.db.add_attachment(ident, 'root', ident, 'fake', ['fake'], self.repo, 'owner')
            self.db.set_attachment_status(ident, 'running', 'owner')
            result = leases.acquire(self.db, 'root', 'gpu', ident)
            self.assertEqual(result['position'], 2 if ident == 'third' else 3)
        # Retirement may delete a line after stopping its processes; the DB
        # cleanup also handles deletion while obsolete attachment rows remain.
        self.db._exec('DELETE FROM conversations WHERE id=?', (self.conv_id,))
        await maintain(self.runtime)
        self.assertEqual(self.claims()['holder']['attachment_id'], 'third')
        leases.release(self.db, 'root', 'gpu', 'third')
        self.assertEqual(self.claims()['holder']['attachment_id'], 'fourth')

    async def test_grant_checks_stale_holder_before_new_acquire_and_retries_interrupted_notice(self):
        self.acquire()
        self.acquire(self.second)
        self.db._exec('DROP TRIGGER line_resource_attachment_delete')
        self.db._exec('DELETE FROM attachments WHERE id=?', (self.first.attachment_id,))
        self.db.add_attachment('late', 'root', 'late', 'fake', ['fake'], self.repo, 'owner')
        self.db.set_attachment_status('late', 'running', 'owner')
        result = leases.acquire(self.db, 'root', 'gpu', 'late')
        self.assertEqual(result['holder']['attachment_id'], 'inspect')
        self.assertEqual(result['position'], 1)
        self.db._exec('UPDATE line_resource_claims SET notified=2 WHERE notice_id IS NOT NULL')
        await maintain(self.runtime)
        self.assertEqual(len([m for m in self.db.list_messages(self.conv_id)
                              if 'you now hold gpu' in m['body']]), 1)
        with self.assertRaises(HTTPException):
            leases.acquire(self.db, 'root', 'missing', 'late')

    async def test_captain_mcp_and_dispatcher_resources_operation(self):
        from unittest.mock import Mock
        from partyline.mcp import tools_captain
        client = Mock(home='root')
        state = {'kind': 'machine', 'role': 'lead', 'is_lead': True, 'actions': ['assign']}
        args = {'conv_id': 'root', 'operation': 'declare', 'name': 'port-8000'}
        tools_captain.call(client, 'resources', args, state)
        client.request.assert_called_with('POST', '/api/conversations/root/resources',
                                          {'operation': 'declare', 'name': 'port-8000'})
        tools_captain.call(client, 'captain', {'op': 'resources', 'args': {
            'conv_id': 'root', 'operation': 'list'}}, state)
        client.request.assert_called_with('POST', '/api/conversations/root/resources', {'operation': 'list'})


class ResourceProbeTest(LineResourcesTest):
    async def test_probes_run_without_database_lock_or_transaction(self):
        checked = []

        def check(name):
            self.assertFalse(self.db.lock.locked())
            self.assertFalse(self.db.conn.in_transaction)
            checked.append(name)

        with patch('partyline.line_resources.probe', side_effect=check):
            self.acquire()
            self.acquire(self.second)
            await maintain(self.runtime)
            self.release()
        self.assertGreaterEqual(checked.count('gpu'), 4)
        self.assertEqual(self.claims()['holder']['attachment_id'], 'inspect')

    async def test_probe_commands_refuse_without_queueing(self):
        import json
        import os
        import sys

        def setting(code):
            return {"PARTYLINE_RESOURCE_PROBES": json.dumps({"gpu": [sys.executable, '-c', code]})}

        with patch.dict(os.environ, setting("print('healthy')")):
            self.assertEqual(self.acquire().json()['status'], 'held')
        for code in ("raise SystemExit(1)", "print('  ')", "import time; time.sleep(5)"):
            with self.subTest(code=code), patch.dict(os.environ, setting(code)):
                response = self.acquire(self.second)
                self.assertEqual(response.status_code, 503)
                self.assertIn('retry', response.json()['detail'])
                self.assertEqual(self.claims()['queue'], [])
        with patch.dict(os.environ, {"PARTYLINE_RESOURCE_PROBES": '{"gpu":["missing-probe-xyz"]}'}):
            self.assertEqual(self.acquire(self.second).json()['status'], 'queued')

    async def test_waiter_is_not_granted_until_probe_recovers(self):
        import os
        self.acquire()
        self.acquire(self.second)
        with patch.dict(os.environ, {"PARTYLINE_RESOURCE_PROBES": '{"gpu":["false"]}'}):
            self.release()
            self.assertIsNone(self.claims()['holder'])
            self.assertEqual(len(self.claims()['queue']), 1)
        with patch.dict(os.environ, {"PARTYLINE_RESOURCE_PROBES": '{"gpu":["missing-probe-xyz"]}'}):
            await maintain(self.runtime)
            self.assertEqual(self.claims()['holder']['attachment_id'], 'inspect')
