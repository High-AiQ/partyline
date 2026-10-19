"""Task return notices stay between peers and never create an implicit loop."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline.goal_stall import GoalStallGuard
from partyline.orchestrator_contracts import ReviewRequestIn, VerdictIn
from partyline.orchestrator_service import request_review, review_verdict
from partyline.return_path import ReturnPath
from tests.orchestrator_fixture import TaskFixture


class RoutingTest(TaskFixture):
    async def open_review(self):
        await self.create()
        sha = self.commit()
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=sha, what='feature', where='code'))
        return self.row()

    async def test_implementer_return_goes_to_reviewer_instead_of_root(self):
        row = await self.open_review()
        returns = ReturnPath(self.runtime)
        returns.grace = 0
        returns.requesters[self.worker.attachment_id] = {'captain': self.db.get_attachment('captain')}
        returns.last_said[self.worker.attachment_id] = 'ready @captain'
        with patch('partyline.return_path.wait_until_quiet', AsyncMock(return_value=True)):
            notices = await returns._settle(self.worker.attachment_id)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['audience_attachment_id'], row['reviewer_id'])
        self.assertEqual(notices[0]['conv_id'], self.conv_id)
        self.assertNotIn('@captain', notices[0]['body'])
        returns.note_delivered(row['reviewer_id'], notices)
        self.assertNotIn(row['reviewer_id'], returns.real_wake)
        await returns.turn_ended(row['reviewer_id'])
        self.assertFalse(returns.pending)

    async def test_structured_request_silent_reviewer_returns_to_implementer(self):
        row = await self.open_review()
        returns = ReturnPath(self.runtime)
        returns.grace = 0
        messages, _ = self.db.message_page(self.conv_id, limit=100)
        request = next(m for m in messages if 'Review round' in m['body'])
        returns.note_delivered(row['reviewer_id'], [request])
        self.assertIn(row['reviewer_id'], returns.real_wake)
        with patch('partyline.return_path.wait_until_quiet', AsyncMock(return_value=True)):
            await returns.turn_ended(row['reviewer_id'])
            await returns.drain()
        messages, _ = self.db.message_page(self.conv_id, limit=100)
        self.assertTrue(any(m['body'].startswith('↩') and
                            m['audience_attachment_id'] == self.worker.attachment_id for m in messages))
        root, _ = self.db.message_page('root', limit=100)
        self.assertFalse(any(m['body'].startswith('↩') for m in root))

    async def test_terminal_task_and_captain_policy_have_no_implicit_return(self):
        row = await self.open_review()
        reviewer = self.principal(row['reviewer_id'])
        await review_verdict(self.runtime, reviewer, self.conv_id,
                             VerdictIn(verdict='approve', findings='verified'))
        returns = ReturnPath(self.runtime)
        returns.grace = 0
        returns.requesters[reviewer.attachment_id] = {'captain': self.db.get_attachment('captain')}
        with patch('partyline.return_path.wait_until_quiet', AsyncMock(return_value=True)):
            self.assertEqual(await returns._settle(reviewer.attachment_id), [])
        await self.create('captain')
        returns.requesters[self.worker.attachment_id] = {'captain': self.db.get_attachment('captain')}
        with patch('partyline.return_path.wait_until_quiet', AsyncMock(return_value=True)):
            self.assertEqual(await returns._settle(self.worker.attachment_id), [])

    async def test_goal_stall_guard_never_wakes_root_for_open_orchestrator_tasks(self):
        await self.open_review()
        self.db._exec("UPDATE conversations SET goal='ship the feature' WHERE id='root'")
        presence = SimpleNamespace()
        guard = GoalStallGuard(self.runtime, presence)
        await guard.check(self.conv_id)
        await guard.check('root')
        self.assertFalse(guard.pending)

    async def test_task_and_orchestrator_packs_describe_their_actual_policy(self):
        from partyline.orchestrator_pack import task_pack
        from partyline.role_briefing import role_instructions
        from partyline.role_delivery import current_role, _instructions
        self.assertEqual(task_pack(None, 'missing', 'implementer'), '')
        self.assertEqual(task_pack(self.db, 'root', 'lead'), '')
        pack = role_instructions(['assign'], 'root', None, captain_mode='orchestrator')
        self.assertIn('reviewer', pack)
        self.assertIn('approval IS acceptance', pack)
        self.assertNotIn('Worked example', pack)
        row = await self.open_review()
        state = current_role(self.db, row['reviewer_id'])
        self.assertEqual(state.role, 'reviewer')
        self.assertIn('You are the reviewer', _instructions(state, self.db))
        self.assertIn('never', _instructions(state, self.db).lower())

    async def test_structured_handoffs_settle_return_debt_without_duplicate_notices(self):
        row = await self.open_review()
        returns = self.runtime.returns = ReturnPath(self.runtime)
        reviewer = self.principal(row['reviewer_id'])
        returns.requesters[reviewer.attachment_id] = {
            self.worker.attachment_id: self.db.get_attachment(self.worker.attachment_id)}
        returns.real_wake.add(reviewer.attachment_id)
        await review_verdict(self.runtime, reviewer, self.conv_id,
                             VerdictIn(verdict='changes', findings='fix edge case'))
        await returns.turn_ended(reviewer.attachment_id)
        self.assertFalse(returns.pending)
        returns.requesters[self.worker.attachment_id] = {
            reviewer.attachment_id: self.db.get_attachment(reviewer.attachment_id)}
        returns.real_wake.add(self.worker.attachment_id)
        sha = self.commit('fix')
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=sha, what='fixed', where='tests'))
        await returns.turn_ended(self.worker.attachment_id)
        self.assertFalse(returns.pending)
        messages, _ = self.db.message_page(self.conv_id, limit=100)
        self.assertFalse(any(m['body'].startswith('↩') for m in messages))

    async def test_compaction_retains_task_role_sha_and_review_request(self):
        from partyline.rebrief import render_rebrief
        row = await self.open_review()
        text = render_rebrief(self.db, self.db.get_attachment(row['reviewer_id']))
        self.assertIn('You are the reviewer', text)
        self.assertIn(row['sha'], text)
        self.assertIn(row['review_worktree'], text)
        self.assertNotIn("edit only on your captain's", text)
        self.assertLessEqual(len(text), 4000)
        text = render_rebrief(self.db, self.db.get_attachment(row['implementer_id']))
        self.assertIn('You are the implementer', text)
