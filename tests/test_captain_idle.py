"""Turn receipts report stranded work without a timer or a wake loop."""

import asyncio
import time
from unittest.mock import AsyncMock, patch

from partyline.presence import Presence
from tests.orchestrator_fixture import TaskFixture


class CaptainIdleTest(TaskFixture):
    async def setup_tree(self):
        await self.create()
        self.presence = Presence(self.runtime)
        self.captain_row = self.db.get_attachment('captain')

    async def end(self):
        await self.presence.returns.turn_ended('captain')

    def notices(self):
        return [row for row in self.db.messages_after('root', 0)
                if 'Nothing is running or scheduled' in row['body']]

    async def test_idle_once_then_changed_and_notice_wake_does_not_loop(self):
        await self.setup_tree()
        with patch('asyncio.sleep', side_effect=AssertionError('timer')), \
             patch.object(asyncio.get_running_loop(), 'call_later', side_effect=AssertionError('timer')):
            await self.end()
            self.assertEqual(len(self.notices()), 2)
            private = self.notices()[1]
            self.assertEqual(private['audience_attachment_id'], 'captain')
            self.presence = Presence(self.runtime)  # a server restart keeps the verdict
            self.presence.returns.note_delivered('captain', [private])
            await self.end()
            self.assertEqual(len(self.notices()), 2)
            self.db._exec("UPDATE task_reviews SET status='blocked' WHERE conv_id=?", (self.conv_id,))
            await self.end()
            self.assertEqual(len(self.notices()), 4)

    async def test_busy_wait_and_reattach_suppress(self):
        await self.setup_tree()
        worker = self.worker.attachment_id
        await self.presence.started(self.conv_id, worker)
        await self.end()
        self.assertEqual(self.notices(), [])
        await self.presence.finished(self.conv_id, worker)
        self.db._exec('UPDATE task_reviews SET wait_until=? WHERE conv_id=?',
                      (time.time() + 100, self.conv_id))
        await self.end()
        self.assertEqual(self.notices(), [])
        self.db._exec('UPDATE task_reviews SET wait_until=NULL WHERE conv_id=?', (self.conv_id,))
        self.presence.queue.hold(worker, [{"id": 1}])
        await self.end()
        self.assertEqual(self.notices(), [])
        self.presence.queue.release(worker, [{"id": 1}])
        self.presence.returns.pending[worker] = object()
        await self.end()
        self.assertEqual(self.notices(), [])
        self.presence.returns.pending.clear()
        self.runtime.reattaching.add(worker)
        await self.end()
        self.assertEqual(self.notices(), [])
        self.runtime.reattaching.clear()
        await self.end()
        self.assertEqual(len(self.notices()), 2)

    async def test_empty_and_integrated_board_are_silent(self):
        await self.setup_tree()
        self.db._exec("UPDATE task_reviews SET status='approved',merged=1 WHERE conv_id=?", (self.conv_id,))
        await self.end()
        self.assertEqual(self.notices(), [])

    async def test_report_and_approval_are_open_without_tasks(self):
        await self.setup_tree()
        self.db._exec("UPDATE task_reviews SET status='done' WHERE conv_id=?", (self.conv_id,))
        self.db._exec("INSERT INTO line_reports(parent_conv_id,child_conv_id,author,body,notify,created_at) "
                      "VALUES('root',?,'worker','ready',1,1)", (self.conv_id,))
        self.db._exec("INSERT INTO conversation_write_grant_requests"
                      "(conv_id,id,path,requester,created_at) VALUES(?, 'request', '/work', 'worker', 1)",
                      (self.conv_id,))
        await self.end()
        self.assertEqual(len(self.notices()), 2)
        self.assertIn('pending report', self.notices()[0]['body'])
        self.assertIn('write-set approval', self.notices()[0]['body'])

    async def test_worker_activity_resets_verdict_even_if_already_finished(self):
        await self.setup_tree()
        await self.end()
        worker = self.worker.attachment_id
        await self.presence.started(self.conv_id, worker)
        await self.presence.finished(self.conv_id, worker)
        await self.end()
        self.assertEqual(len(self.notices()), 4)

    async def test_busy_turn_resets_verdict_and_captain_queue_suppresses(self):
        await self.setup_tree()
        await self.end()
        worker = self.worker.attachment_id
        self.presence.queue.hold(worker, [{'id': 1}])
        await self.end()
        self.presence.queue.release(worker, [{'id': 1}])
        self.presence.queue.hold('captain', [{'id': 2}])
        await self.end()
        self.assertEqual(len(self.notices()), 2)
        self.presence.queue.release('captain', [{'id': 2}])
        await self.end()
        self.assertEqual(len(self.notices()), 4)

    async def test_empty_board_without_task_rows(self):
        self.presence = Presence(self.runtime)
        await self.end()
        self.assertEqual(self.notices(), [])

    async def test_check_failure_does_not_break_return_path(self):
        await self.setup_tree()
        with patch('partyline.captain_idle.check', side_effect=RuntimeError('broken')):
            with self.assertLogs('partyline.captain_idle', level='ERROR'):
                await self.end()
        self.assertIn('captain', self.presence.returns.ended_at)

    async def test_heartbeat_that_will_wake_suppresses_alert(self):
        from partyline import heartbeat

        await self.setup_tree()
        heartbeat.enable(self.db, 'root', 'captain', quiet_if_unchanged=False)
        with patch('partyline.captain_idle.features.enabled', return_value=True), \
             patch('partyline.heartbeat_scheduler.deliverable_owner', return_value=self.captain_row):
            await self.end()
        self.assertEqual(self.notices(), [])
        await self.end()
        self.assertEqual(len(self.notices()), 2)

    async def test_quiet_heartbeat_is_only_a_wake_when_actionable(self):
        from partyline import heartbeat

        await self.setup_tree()
        heartbeat.enable(self.db, 'root', 'captain', quiet_if_unchanged=True)
        with patch('partyline.captain_idle.features.enabled', return_value=True), \
             patch('partyline.heartbeat_scheduler.deliverable_owner', return_value=self.captain_row), \
             patch('partyline.heartbeat_snapshot.build', return_value={}), \
             patch('partyline.heartbeat_snapshot.is_actionable', return_value=True):
            await self.end()
        self.assertEqual(self.notices(), [])
        with patch('partyline.captain_idle.features.enabled', return_value=True), \
             patch('partyline.heartbeat_scheduler.deliverable_owner', return_value=self.captain_row), \
             patch('partyline.heartbeat_snapshot.build', return_value={}), \
             patch('partyline.heartbeat_snapshot.is_actionable', return_value=False):
            await self.end()
        self.assertEqual(len(self.notices()), 2)

    async def test_failed_delivery_can_be_retried(self):
        await self.setup_tree()
        with patch('partyline.captain_idle.post_private', side_effect=RuntimeError('broken')):
            with self.assertLogs('partyline.captain_idle', level='ERROR'):
                await self.end()
        await self.end()
        self.assertEqual(len(self.notices()), 3)

    async def test_deferred_return_to_captain_suppresses_alert(self):
        await self.setup_tree()
        self.presence.returns.deferred['captain'] = [
            ('root', '↩ @captain worker finished', self.worker.attachment_id),
        ]
        await self.end()
        self.assertEqual(self.notices(), [])
        self.assertTrue(any('worker finished' in row['body']
                            for row in self.db.messages_after('root', 0)))

    async def test_agent_wake_with_owed_return_still_alerts_immediately(self):
        await self.setup_tree()
        returns = self.presence.returns
        worker = self.db.get_attachment(self.worker.attachment_id)
        returns.note_delivered('captain', [{'id': 999, 'body': '@captain done',
                                           'sender': worker['name'], 'sender_type': 'agent',
                                           'source_conv_id': self.conv_id}])
        self.db._exec("UPDATE attachments SET status='detached' WHERE id=?", (worker['id'],))
        returns.sleep = AsyncMock()
        with patch('partyline.return_path.wait_until_quiet', new=AsyncMock(return_value=True)), \
             patch('asyncio.sleep', side_effect=AssertionError('timer')), \
             patch.object(asyncio.get_running_loop(), 'call_later', side_effect=AssertionError('timer')):
            await self.end()
            self.assertEqual(len(self.notices()), 2)
            await returns.drain()
            self.assertEqual(len(self.notices()), 2)

    async def test_existing_pending_return_does_not_hide_idle_verdict(self):
        await self.setup_tree()
        pending = asyncio.get_running_loop().create_future()
        self.presence.returns.pending['captain'] = pending
        await self.end()
        self.assertEqual(len(self.notices()), 2)
        self.presence.returns.pending.pop('captain')
        pending.cancel()

    async def test_detached_captain_verdict_is_pruned(self):
        await self.setup_tree()
        await self.end()
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='captain'")
        row = self.db._exec("SELECT * FROM captain_idle_verdicts WHERE attachment_id='captain'").fetchone()
        self.assertIsNone(row)

    async def test_pending_return_to_descendant_captain_is_a_scheduled_wake(self):
        await self.setup_tree()
        self.db.create_conversation('sub', 'Sub')
        self.db._exec("UPDATE conversations SET parent_id='root',captain_mode='manager_tree' WHERE id='sub'")
        self.db.add_attachment('subcaptain', 'sub', 'subcaptain', 'fake', ['fake'], self.repo, 'owner')
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='subcaptain'")
        self.runtime.live['subcaptain'] = self.runtime.live['captain']
        pending = asyncio.get_running_loop().create_future()
        self.presence.returns.pending['captain'] = pending
        self.presence.returns.requesters['captain'] = {'subcaptain': self.db.get_attachment('subcaptain')}
        await self.end()
        self.assertEqual(self.notices(), [])
        self.presence.returns.pending.pop('captain')
        pending.cancel()
