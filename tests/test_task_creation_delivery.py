"""Creation retries and interrupted setup keep one durable, readable task goal."""

import asyncio
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from partyline.db import Db
from partyline.mcp.server import MCPServer
from partyline.orchestrator_contracts import TaskIn
from partyline.orchestrator_service import create_task
from partyline.orchestrator_store import tasks
from partyline.role_delivery import bind_role_delivery
from tests.orchestrator_fixture import TaskFixture


class CreationDeliveryTest(TaskFixture):
    async def test_large_goal_round_trips_http_and_restart(self):
        goal = 'Detailed requirement.\n' * 400
        result = self.client.post('/api/conversations/root/tasks', json={
            'name': 'large', 'goal': goal, 'implementer': 'builder'})
        self.assertEqual(result.status_code, 201, result.text)
        row = result.json()
        self.assertEqual(row['goal'], goal.strip())
        reopened = Db(self.db.path)
        self.addCleanup(reopened.close)
        att = {'id': row['implementer_id'], 'digest_rider': lambda: ''}
        bind_role_delivery(reopened, att)
        self.assertIn('Detailed requirement.', att['digest_rider']())
        detail = self.client.get(f"/api/conversations/{row['conv_id']}/task").json()
        self.assertEqual(detail['goal'], goal.strip())

    async def test_retry_after_lost_mcp_response_returns_running_task(self):
        arguments = {'name': 'slice', 'goal': 'Build the feature', 'implementer': 'builder'}
        row = await create_task(self.runtime, self.captain, 'root', TaskIn(**arguments))
        client = SimpleNamespace(home='root', connection={'api': 'http://lan.example:8642'},
                                 capabilities=lambda: {'actions': ['create_task']},
                                 request=Mock(side_effect=TimeoutError('timed out')))
        output = io.StringIO()
        MCPServer(client, output).handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'create_task', 'arguments': arguments}})
        error = json.loads(output.getvalue())['result']['content'][0]['text']
        self.assertIn('same name', error)
        retry = await create_task(self.runtime, self.captain, 'root', TaskIn(**arguments))
        self.assertEqual(retry['conv_id'], row['conv_id'])
        self.assertEqual(len(tasks(self.db, 'root')), 1)
        self.assertEqual(len(self.db.list_attachments(row['conv_id'])), 1)

    async def test_concurrent_creates_share_identity(self):
        body = TaskIn(name='same', goal='one assignment', implementer='builder')
        first, second = await asyncio.gather(*(
            create_task(self.runtime, self.captain, 'root', body) for _ in range(2)))
        self.assertEqual(first['conv_id'], second['conv_id'])
        self.assertEqual(len(tasks(self.db, 'root')), 1)

    async def test_goal_is_durable_before_first_await_after_line_insert(self):
        async def interrupted_placement(*args):
            raise asyncio.CancelledError()
        original = asyncio.to_thread
        with patch('partyline.child_create.asyncio.to_thread', wraps=original) as threaded:
            async def run(function, *args):
                if function.__name__ == 'place_task':
                    return await interrupted_placement()
                return await original(function, *args)
            threaded.side_effect = run
            with self.assertRaises(asyncio.CancelledError):
                await create_task(self.runtime, self.captain, 'root', TaskIn(
                    name='interrupted', goal='persistent direction', implementer='builder'))
        reopened = Db(self.db.path)
        self.addCleanup(reopened.close)
        child = reopened._exec("SELECT * FROM conversations WHERE parent_id='root'").fetchone()
        self.assertEqual(child['goal'], 'persistent direction')

    async def test_failed_paste_does_not_consume_task_goal(self):
        row = await self.create()
        att = {'id': row['implementer_id'], 'digest_rider': lambda: ''}
        bind_role_delivery(self.db, att)
        self.assertIn('(task goal: Build the feature)', att['digest_rider']())
        # Digest construction can precede a failed PTY paste; a retry needs the goal too.
        self.assertIn('(task goal: Build the feature)', att['digest_rider']())

    async def test_assignment_before_transcript_claim_survives_hello_and_retry(self):
        from partyline.adapters.base import Adapter
        from partyline.presence import Presence

        row = await self.create()
        ident, conv = row['implementer_id'], row['conv_id']
        att = self.db.get_attachment(ident)
        att['adapter_metadata'] = {'capabilities': {'transcript': True},
                                   'delivery_proof': 'transcript-user-record'}
        att['digest_rider'] = lambda: ''
        bind_role_delivery(self.db, att)
        # The joining prompt must already contain direction during the hello turn.
        self.assertIn('Build the feature', att['role_briefing'])
        adapter = Adapter(att, Mock(), Mock())
        pastes = []
        adapter.send_keys = self._recording_keys(pastes)
        presence = Presence(self.runtime)
        watched = presence.watch(adapter, conv, ident, 'receipt',
                                  *self.runtime.held_wake_hooks(conv, ident, att['name']))
        self.runtime.live[ident] = watched
        await presence.started(conv, ident, att['runtime_owner'])
        await self.runtime.deliver_pending(conv, self.db.get_attachment(ident), watched)
        self.assertIn(ident, self.runtime.uncredited)
        self.assertTrue(any('Implement this task' in text for text in pastes))
        adapter.mark_ready()
        await asyncio.sleep(0)
        self.assertTrue(presence.queue.held_ids(ident))
        before = len(pastes)
        # The structured end of the joining hello releases the pre-claim assignment.
        await presence.ended(conv, ident, att['runtime_owner'])
        self.assertGreater(len(pastes), before)
        self.assertIn('Implement this task', pastes[-1])
        self.assertIn('(task goal: Build the feature)', pastes[-1])

    @staticmethod
    def _recording_keys(pastes):
        async def send(text):
            pastes.append(text)
        return send

    async def test_conflicting_assignment_refuses_existing_name(self):
        await self.create()
        result = self.client.post('/api/conversations/root/tasks', json={
            'name': 'slice', 'goal': 'different direction', 'implementer': 'builder'})
        self.assertEqual(result.status_code, 409, result.text)
        self.assertIn(self.conv_id, result.text)
        self.assertEqual(len(tasks(self.db, 'root')), 1)

    async def test_mcp_goal_limits_reject_before_request_and_accept_full_limit(self):
        from partyline.mcp import tools_tasks

        client = SimpleNamespace(home='root', request=Mock(return_value={}))
        state = {'actions': ['create_task']}
        arguments = {'name': 'limit', 'goal': 'x' * 20001, 'implementer': 'builder'}
        with self.assertRaisesRegex(ValueError, 'goal is capped at 20000 characters'):
            tools_tasks.call(client, 'create_task', arguments, state)
        client.request.assert_not_called()
        result = self.client.post('/api/conversations/root/tasks', json=arguments)
        self.assertEqual(result.status_code, 422)
        self.assertEqual(tasks(self.db, 'root'), [])
        for size in (3100, 8400, 20000):
            with self.subTest(size=size):
                arguments['goal'] = 'x' * size
                tools_tasks.call(client, 'create_task', arguments, state)
                self.assertEqual(len(client.request.call_args.args[2]['goal']), size)
        result = self.client.post('/api/conversations/root/tasks', json=arguments)
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()['goal'], arguments['goal'])

    async def test_notification_failure_still_returns_created_line(self):
        from unittest.mock import AsyncMock

        with patch('partyline.orchestrator_service.tell', AsyncMock(side_effect=OSError('unavailable'))):
            row = await create_task(self.runtime, self.captain, 'root', TaskIn(
                name='delivery', goal='persistent goal', implementer='builder'))
        self.assertIn('unavailable', row['creation_error'])
        self.assertEqual(row['goal'], 'persistent goal')
        self.assertEqual(len(tasks(self.db, 'root')), 1)
        self.assertEqual(self.db.get_attachment(row['implementer_id'])['status'], 'running')

    async def test_child_announcement_failure_returns_reserved_task(self):
        from unittest.mock import AsyncMock

        self.runtime.broadcast_all = AsyncMock(side_effect=OSError('broadcast unavailable'))
        with self.assertLogs('partyline.orchestrator_service', level='ERROR'):
            row = await create_task(self.runtime, self.captain, 'root', TaskIn(
                name='announce', goal='persistent goal', implementer='builder'))
        self.assertIn('broadcast unavailable', row['creation_error'])
        self.assertEqual(len(tasks(self.db, 'root')), 1)
        self.assertEqual(self.db.get_attachment(row['implementer_id'])['status'], 'running')

    async def test_proven_second_wake_omits_goal_until_change_or_restart(self):
        from partyline.orchestrator_goal import set_task_goal

        row = await self.create()
        ident = row['implementer_id']
        adapter = self.runtime.live[ident]
        adapter._ready_result = False
        att = {'id': ident, 'digest_rider': lambda: ''}
        bind_role_delivery(self.db, att, self.runtime)
        full = '(task goal: Build the feature)'
        self.assertIn(full, att['digest_rider']())
        self.assertIn(full, att['digest_rider']())
        owner = self.db.get_attachment(ident)['runtime_owner']
        latest = self.db.list_messages(row['conv_id'])[-1]['id']
        self.db.set_last_seen(ident, latest, owner)
        self.assertIn(full, att['digest_rider']())  # a cursor without a claim is insufficient
        adapter._ready_result = True
        self.assertNotIn(full, att['digest_rider']())
        changed = 'New detailed requirement. ' * 400
        await set_task_goal(self.runtime, self.captain, row['conv_id'], changed)
        self.assertIn(changed.strip(), att['digest_rider']())
        self.assertIn(changed.strip(), att['digest_rider']())
        latest = self.db.list_messages(row['conv_id'])[-1]['id']
        self.db.set_last_seen(ident, latest, owner)
        self.assertNotIn(changed.strip(), att['digest_rider']())
        restarted = {'id': ident, 'digest_rider': lambda: ''}
        bind_role_delivery(self.db, restarted, self.runtime)
        self.assertIn(changed.strip(), restarted['digest_rider']())
