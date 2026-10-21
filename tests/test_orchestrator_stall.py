"""A missing structured task result recovers once, then reports the stall."""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from partyline.db import Db
from partyline.machine_scope import allows
from partyline.mcp.tools_tasks import tool_list
from partyline.orchestrator_contracts import BlockedIn, ReviewRequestIn
from partyline.orchestrator_notices import report
from partyline.orchestrator_service import request_review
from partyline.orchestrator_stall import began, blocked, ended
from partyline.return_path import ReturnPath
from tests.orchestrator_fixture import TaskFixture


class StallTest(TaskFixture):
    def messages(self, conv):
        return self.db.message_page(conv, limit=100)[0]

    async def end(self, returns):
        with patch('partyline.return_path.wait_until_quiet', AsyncMock(return_value=True)):
            await returns.turn_ended(self.worker.attachment_id)
            await returns.drain()

    async def test_no_peer_reminds_once_then_reports_once_for_every_policy(self):
        for policy in ('none', 'captain', 'inspector'):
            with self.subTest(policy=policy):
                await self.create(policy)
                returns = self.runtime.returns = ReturnPath(self.runtime)
                returns.grace = 0
                # Even a chat hand-off cannot substitute for the structured call.
                returns.note_spoke(self.worker.attachment_id, '@captain done')
                await self.end(returns)
                self.assertEqual(self.row()['stall_stage'], 1)
                notices = [m for m in self.messages(self.conv_id) if 'no hand-off' in m['body']]
                self.assertEqual(len(notices), 1)
                self.assertEqual(notices[0]['audience_attachment_id'], self.worker.attachment_id)
                # Duplicate receipts before reminder delivery cannot escalate or loop.
                await self.end(returns)
                self.assertIsNone(self.row()['report_id'])
                self.assertEqual(self.row()['stall_stage'], 1)
                returns.note_delivered(self.worker.attachment_id, notices)
                self.assertEqual(self.row()['stall_stage'], 2)
                await self.end(returns)
                row = self.row()
                self.assertEqual(row['stall_stage'], 3)
                report_id = row['report_id']
                from partyline.reports import get
                self.assertIn('stalled', get(self.db, report_id)['body'])
                await self.end(returns)
                await report(self.runtime, row)
                self.assertEqual(self.row()['report_id'], report_id)
                self.assertEqual(len([m for m in self.messages(self.conv_id)
                                      if 'no hand-off' in m['body']]), 1)
                root = [m for m in self.messages('root') if f'report {report_id}' in m['body']]
                self.assertEqual(len(root), 1)

    async def test_blocked_is_authorized_deduped_and_can_resume(self):
        await self.create('none')
        self.assertTrue(allows(self.db, self.worker, self.conv_id, 'blocked'))
        self.assertFalse(allows(self.db, self.captain, self.conv_id, 'blocked'))
        self.assertEqual(tool_list({'actions': ['blocked']})[0]['name'], 'blocked')
        with self.assertRaises(HTTPException):
            await blocked(self.runtime, self.captain, self.conv_id, BlockedIn(reason='dependency'))
        returns = self.runtime.returns = ReturnPath(self.runtime)
        returns.grace = 0
        await self.end(returns)
        reminder = next(m for m in self.messages(self.conv_id) if 'no hand-off' in m['body'])
        returns.note_delivered(self.worker.attachment_id, [reminder])
        row = await blocked(self.runtime, self.worker, self.conv_id, BlockedIn(reason='dependency'))
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(self.db.get_conversation(self.conv_id)['task_status'], 'blocked')
        await self.end(returns)
        await blocked(self.runtime, self.worker, self.conv_id, BlockedIn(reason='dependency'))
        self.assertEqual(self.row()['report_id'], row['report_id'])
        root = [m for m in self.messages('root') if f"report {row['report_id']}" in m['body']]
        self.assertEqual(len(root), 1)
        sha = self.commit()
        done = await request_review(self.runtime, self.worker, self.conv_id,
                                    ReviewRequestIn(sha=sha, what='unblocked', where='code'))
        self.assertEqual(done['status'], 'done')
        from partyline.reports import get
        self.assertIn(': done;', get(self.db, done['report_id'])['body'])
        with self.assertRaises(HTTPException):
            await blocked(self.runtime, self.worker, self.conv_id, BlockedIn(reason='late'))

    async def test_structured_attempt_reenters_implementing_even_if_review_fails(self):
        await self.create()
        await blocked(self.runtime, self.worker, self.conv_id, BlockedIn(reason='missing commit'))
        with self.assertRaises(HTTPException):
            await request_review(self.runtime, self.worker, self.conv_id,
                                 ReviewRequestIn(sha='deadbeef', what='attempt', where='code'))
        self.assertEqual(self.row()['status'], 'implementing')
        self.assertEqual(self.row()['stall_stage'], 0)
        self.assertIsNone(self.row()['report_id'])

    async def test_migration_preserves_existing_review_and_restart_preserves_blocked(self):
        await self.create('captain')
        self.db._exec("UPDATE task_reviews SET status='blocked',stall_stage=2 WHERE conv_id=?",
                      (self.conv_id,))
        reopened = Db(self.db.path)
        try:
            row = reopened._exec('SELECT * FROM task_reviews WHERE conv_id=?',
                                 (self.conv_id,)).fetchone()
            self.assertEqual(row['status'], 'blocked')
            self.assertEqual(row['stall_stage'], 2)
        finally:
            reopened.close()
        # Simulate the pre-widening schema and migration marker on an old DB.
        self.db._exec('DELETE FROM orchestrator_state_migrations')
        self.db._exec("UPDATE task_reviews SET initial_status='in_review' WHERE conv_id=?", (self.conv_id,))
        self.db._exec('ALTER TABLE task_reviews DROP COLUMN status')
        self.db._exec('ALTER TABLE task_reviews DROP COLUMN status_pre_idle')
        self.db._exec('ALTER TABLE task_reviews RENAME COLUMN initial_status TO status')
        reopened = Db(self.db.path)
        try:
            row = reopened._exec('SELECT * FROM task_reviews WHERE conv_id=?', (self.conv_id,)).fetchone()
            self.assertEqual(row['status'], 'in_review')
        finally:
            reopened.close()

    async def test_implementer_is_idle_between_turns_and_implementing_again_on_began(self):
        await self.create('captain')
        att = self.db.get_attachment(self.worker.attachment_id)
        await ended(self.runtime, att)
        self.assertEqual(self.row()['status'], 'idle')
        await began(self.runtime, att)
        self.assertEqual(self.row()['status'], 'implementing')
        # Queued mail means the turn is not over; settled and blocked tasks never turn idle.
        self.db._exec("INSERT INTO queued_delivery_messages(attachment_id,message_id) VALUES(?,1)",
                      (att['id'],))
        await ended(self.runtime, att)
        self.assertEqual(self.row()['status'], 'implementing')
        self.db._exec('DELETE FROM queued_delivery_messages')
        self.db._exec("UPDATE task_reviews SET status='blocked' WHERE conv_id=?", (self.conv_id,))
        await ended(self.runtime, att)
        self.assertEqual(self.row()['status'], 'blocked')

    async def test_idle_implementer_is_still_reminded_and_can_ask_for_review(self):
        await self.create('captain')
        returns = self.runtime.returns = ReturnPath(self.runtime)
        returns.grace = 0
        await ended(self.runtime, self.db.get_attachment(self.worker.attachment_id))
        await self.end(returns)
        self.assertEqual(self.row()['stall_stage'], 1)
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=self.commit(), what='built', where='code'))
        self.assertEqual(self.row()['status'], 'in_review')

    async def test_two_root_leads_do_not_multiply_live_count(self):
        await self.create('captain')
        self.db._exec('DROP INDEX idx_attachments_one_lead')
        self.db.add_attachment('captain2', 'root', 'other', 'fake', ['fake'], self.repo, 'owner')
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='captain2'")
        line = self.db.get_conversation(self.conv_id)
        self.assertEqual(line['live_count'], 1)
        self.assertEqual(line['task_reviewer_name'], 'captain')
        listing = next(c for c in self.db.list_conversations() if c['id'] == self.conv_id)
        self.assertEqual(listing['live_count'], 1)

    async def test_blocked_http_and_mcp_require_the_assigned_implementer(self):
        from partyline.mcp.tools_tasks import call
        from partyline.mcp.client import ApiError
        from unittest.mock import Mock
        await self.create()
        url = f'/api/conversations/{self.conv_id}/blocked'
        self.actor = self.captain
        self.assertEqual(self.client.post(url, json={'reason': 'dependency'}).status_code, 403)
        self.actor = self.human
        self.assertEqual(self.client.post(url, json={'reason': 'dependency'}).status_code, 403)
        self.actor = self.worker
        for reason in ('', '   '):
            self.assertEqual(self.client.post(url, json={'reason': reason}).status_code, 422)
        response = self.client.post(url, json={'reason': 'dependency'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'blocked')
        client = Mock(home=self.conv_id)
        call(client, 'blocked', {'reason': 'dependency'}, {'actions': ['blocked']})
        client.request.assert_called_once_with('POST', url, {'reason': 'dependency'})
        with self.assertRaises(ApiError):
            call(client, 'blocked', {'reason': 'dependency'}, {'actions': []})

    async def test_delivered_reminder_survives_return_path_restart(self):
        await self.create('captain')
        returns = ReturnPath(self.runtime)
        returns.grace = 0
        await self.end(returns)
        notice = next(m for m in self.messages(self.conv_id) if 'no hand-off' in m['body'])
        returns = ReturnPath(self.runtime)
        returns.grace = 0
        returns.note_delivered(self.worker.attachment_id, [notice])
        await self.end(returns)
        self.assertEqual(self.row()['stall_stage'], 3)
        row = await blocked(self.runtime, self.worker, self.conv_id, BlockedIn(reason='dependency'))
        from partyline.reports import get
        self.assertEqual(row['status'], 'blocked')
        self.assertIn(': blocked;', get(self.db, row['report_id'])['body'])

    async def test_reminder_identity_is_saved_before_synchronous_delivery(self):
        await self.create('none')
        returns = ReturnPath(self.runtime)
        returns.grace = 0
        async def deliver(conv_id, notice, **kwargs):
            returns.note_delivered(self.worker.attachment_id, [notice])
        self.runtime.route_mentions.side_effect = deliver
        await self.end(returns)
        self.assertEqual(self.row()['stall_stage'], 2)
        await self.end(returns)
        self.assertEqual(self.row()['stall_stage'], 3)
