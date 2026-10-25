"""A SHA quoted in a report must be a commit in the task's worktrees, or be flagged."""

from unittest.mock import AsyncMock, patch

from partyline.orchestrator_contracts import BlockedIn, ReviewRequestIn, VerdictIn
from partyline.orchestrator_service import request_review, review_verdict
from partyline.orchestrator_sha_check import flagged, suspected
from partyline.orchestrator_stall import blocked
from partyline.reports import get
from partyline.return_path import ReturnPath
from tests.orchestrator_fixture import TaskFixture

FAKE = '568b2db'


class ShaCheckTest(TaskFixture):
    def root_messages(self):
        return self.db.message_page('root', limit=100)[0]

    def flagged_notices(self):
        return [m for m in self.root_messages() if 'reported SHAs' in m['body']]

    async def escalated(self, prior, reported):
        """Stall to stage 3 with prior findings, then set the server's report text."""
        await self.create('none')
        returns = self.runtime.returns = ReturnPath(self.runtime)
        returns.grace = 0
        with patch('partyline.return_path.wait_until_quiet', AsyncMock(return_value=True)):
            await returns.turn_ended(self.worker.attachment_id)
            await returns.drain()
            reminder = next(m for m in self.db.message_page(self.conv_id, limit=100)[0]
                            if 'no hand-off' in m['body'])
            returns.note_delivered(self.worker.attachment_id, [reminder])
            await returns.turn_ended(self.worker.attachment_id)
            await returns.drain()
        self.assertEqual(self.row()['stall_stage'], 3)
        from partyline.orchestrator_notices import report
        from partyline.orchestrator_store import task
        self.db._exec("UPDATE task_reviews SET findings=? WHERE conv_id=?",
                      (reported, self.conv_id))
        await report(self.runtime, task(self.db, self.conv_id))
        self.db._exec("UPDATE task_reviews SET findings=? WHERE conv_id=?",
                      (prior, self.conv_id))

    def test_suspected_only_takes_bare_hex_tokens(self):
        self.assertEqual(suspected('commit 568b2db landed, B007 B007s deadbeef123'),
                         ['568b2db', 'deadbeef123'])
        self.assertEqual(suspected('no hash in this sentence'), [])
        self.assertEqual(suspected(''), [])

    async def test_a_blocked_reason_claiming_a_missing_commit_is_flagged_to_the_captain(self):
        await self.create('none')
        row = await blocked(self.runtime, self.worker, self.conv_id,
                            BlockedIn(reason=f'files staged at {FAKE}'))
        self.assertEqual(row['status'], 'blocked')
        self.assertIn(FAKE, flagged(self.db, row))
        body = get(self.db, row['report_id'])['body']
        self.assertIn('unverified SHAs', body)
        self.assertIn(FAKE, body)
        self.assertEqual(self.flagged_notices()[0]['audience_attachment_id'], 'captain')

    async def test_a_live_root_captain_is_rung_once_about_a_missing_commit(self):
        await self.create('none')
        await blocked(self.runtime, self.worker, self.conv_id,
                      BlockedIn(reason=f'files staged at {FAKE}'))
        with patch('partyline.orchestrator_sha_check.post_private', new=AsyncMock()) as post:
            from partyline.orchestrator_sha_check import flag
            await flag(self.runtime, self.row(), f'files staged at {FAKE}')
        self.assertEqual(post.call_count, 1)
        self.assertIn(FAKE, post.call_args.args[4])

    async def test_request_review_hands_over_even_when_the_quoted_sha_is_missing(self):
        await self.create('none')
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=self.commit(), what=f'landed {FAKE}',
                                                   where='code'))
        self.assertEqual(row['status'], 'done')
        self.assertIn(FAKE, flagged(self.db, row))
        self.assertIn('unverified SHAs', get(self.db, row['report_id'])['body'])

    async def test_changes_findings_quoting_a_missing_commit_are_flagged(self):
        await self.create('inspector')
        sha = self.commit()
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=sha, what='first', where='code'))
        row = self.row()
        await review_verdict(self.runtime, self.principal(row['reviewer_id']), self.conv_id,
                             VerdictIn(verdict='changes', findings=f'revert {FAKE}'))
        self.assertIn(FAKE, flagged(self.db, self.row()))
        self.assertEqual(len(self.flagged_notices()), 1)
