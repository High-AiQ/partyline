"""A memory approval wakes an idle task with fresh direction after its restart."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline.adapters.base import Adapter
from partyline.memory_requests import register_memory_request_routes
from partyline.resume_continuation import drain, resume_with_backlog
from partyline.role_delivery import bind_role_delivery
from tests.orchestrator_fixture import TaskFixture


class MemoryApprovalGoalTest(TaskFixture):
    async def test_approval_restarts_idle_task_with_goal_and_continuation(self):
        row = await self.create()
        ident = row['implementer_id']
        prior = {'id': ident, 'digest_rider': lambda: ''}
        self.runtime.live[ident]._ready_result = True
        bind_role_delivery(self.db, prior, self.runtime)
        self.assertIn('Build the feature', prior['digest_rider']())
        pastes, startup_batches = [], []

        async def resume(attachment_id, pending):
            self.assertEqual(attachment_id, ident)
            self.db._exec("UPDATE attachments SET status='running',runtime_owner='new-owner' WHERE id=?",
                          (ident,))
            att = self.db.get_attachment(ident)
            self.assertEqual(att['memory_limit'], '5G')
            att['digest_rider'] = lambda: ''
            att['adapter_metadata'] = {'capabilities': {'transcript': True, 'resume': True}}
            bind_role_delivery(self.db, att, self.runtime)
            adapter = Adapter(att, AsyncMock(), AsyncMock())
            adapter.send_keys = AsyncMock(side_effect=lambda text: pastes.append(text))
            self.runtime.live[ident] = adapter
            adapter.mark_ready()
            startup_batches.append(pending)
            return SimpleNamespace(adapter=adapter, startup_delivery_staged=False)

        async def resume_and_settle(runtime, attachment_id, callback):
            result = await resume_with_backlog(runtime, attachment_id, callback)
            await drain()
            return result

        register_memory_request_routes(self.app, self.runtime, resume)
        self.db.set_setting('default_process_memory_bytes', str(1024**3))
        self.db.set_setting('memory_captain_ceiling_bytes', str(6 * 1024**3))
        with (patch('partyline.memory_requests.memory_ceiling', return_value=64 * 1024**3),
              patch.dict('partyline.memory_requests.ADAPTER_METADATA',
                         {'fake': {'capabilities': {'resume': True}}}),
              patch('partyline.memory_requests.resume_with_backlog', side_effect=resume_and_settle)):
            self.actor = self.worker
            filed = self.client.post(f'/api/attachments/{ident}/memory-requests', json={
                'requested_limit': '5G', 'reason': 'larger working set'})
            self.assertEqual(filed.status_code, 200, filed.text)
            # The worker is idle, with no interrupted turn or unread assignment.
            latest = self.db.list_messages(row['conv_id'])[-1]['id']
            self.db.set_last_seen(ident, latest, self.db.get_attachment(ident)['runtime_owner'])
            self.assertNotIn('Build the feature', prior['digest_rider']())
            self.actor = self.captain
            approved = self.client.post(f"/api/memory-requests/{filed.json()['id']}/approve")
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertFalse(approved.json().get('resume_failed'), approved.text)
        self.assertTrue(startup_batches[0], 'memory restart must stage a continuation even when idle')
        self.assertTrue(pastes, 'a non-staging adapter must receive its first continuation wake')
        self.assertIn('(task goal: Build the feature)', pastes[0])
        self.assertIn('new memory cap', pastes[0])
        self.assertIn('continue the task', pastes[0])
        self.assertIn('implementing', pastes[0])
        self.assertIn('round 0', pastes[0])
