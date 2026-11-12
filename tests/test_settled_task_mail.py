"""An approved, accepted or acknowledged task delivers nothing more to its workers."""

from unittest.mock import AsyncMock, patch

from partyline import reports
from partyline.orchestrator_contracts import ReopenIn, ReviewRequestIn, VerdictIn
from partyline.orchestrator_notices import report, tell
from partyline.orchestrator_reopen import reopen_task
from partyline.orchestrator_service import request_review, review_verdict
from partyline.resume_backlog import addressed_backlog
from partyline.runtime import ChatRuntime
from partyline.task_accept import settle_task
from tests.orchestrator_fixture import TaskFixture

STALE = ('Review round', 'no hand-off', 'Changes requested', 'continue the task')


class SettledTaskMail(TaskFixture):
    def setUp(self):
        super().setUp()
        # Real routing: a wake to a worker pastes everything past its cursor.
        self.runtime.route_mentions = ChatRuntime.route_mentions.__get__(self.runtime)
        self.batches = {}
        self.runtime.live['captain'].deliver = AsyncMock(return_value=True)

    async def start(self, att, **kwargs):
        # An unproved paste (no transcript receipt): the cursor stays behind the mail.
        row = await super().start(att, **kwargs)
        batches = self.batches.setdefault(att['id'], [])

        async def deliver(messages):
            batches.append([m['body'] for m in messages])
            return False
        self.runtime.live[att['id']].deliver = deliver
        return row

    def heard(self, ident):
        return [body for batch in self.batches.get(ident, []) for body in batch]

    def stale(self, ident):
        return [body for body in self.heard(ident) if any(word in body for word in STALE)]

    async def reviewed(self, verdict='approve'):
        row = await self.create('inspector')
        sha = self.commit()
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=sha, what='fix', where='code'))
        self.reviewer = self.principal(row['reviewer_id'])
        await review_verdict(self.runtime, self.reviewer, self.conv_id,
                             VerdictIn(verdict=verdict, findings='looks right', sha=sha))
        return row

    async def poke(self, *idents):
        for ident in idents:
            await tell(self.runtime, ident, 'unrelated word from the captain')

    async def test_wake_after_approval_does_not_replay_the_review_request(self):
        row = await self.reviewed()
        reviewer = row['reviewer_id']
        self.assertEqual(len(self.stale(reviewer)), 1)  # the original delivery
        for _ in range(3):
            await self.poke(reviewer)
        self.assertEqual(len(self.stale(reviewer)), 1)
        self.assertTrue(any('unrelated word' in b for b in self.batches[reviewer][-1]))

    async def test_accepted_and_acknowledged_task_stays_quiet_for_both_workers(self):
        row = await self.reviewed()
        record = reports.get(self.db, self.row()['report_id'])
        reports.acknowledge(self.db, record['id'], 'root', record['revision'])
        await settle_task(self.runtime, self.conv_id, self.row())
        seen = {ident: len(self.stale(ident)) for ident in (row['reviewer_id'], row['implementer_id'])}
        await self.poke(row['reviewer_id'], row['implementer_id'])
        for ident, count in seen.items():
            self.assertEqual(len(self.stale(ident)), count)

    async def test_resume_backlog_drops_settled_task_mail_but_keeps_new_mail(self):
        row = await self.reviewed()
        self.db._exec("UPDATE attachments SET last_seen=0 WHERE id=?", (row['reviewer_id'],))
        await tell(self.runtime, row['reviewer_id'], 'fresh word after settling')
        att = self.db.get_attachment(row['reviewer_id'])
        bodies = [m['body'] for m in addressed_backlog(self.runtime, att)]
        self.assertFalse([b for b in bodies if 'Review round' in b])
        self.assertTrue([b for b in bodies if 'fresh word' in b])

    async def test_held_flush_drops_settled_task_mail(self):
        row = await self.reviewed()
        brief = next(m for m in self.db.message_page(self.conv_id, limit=50)[0]
                     if 'Review round' in m['body'])
        att = self.db.get_attachment(row['reviewer_id'])
        flush = self.runtime.held_wake_hooks(self.conv_id, att['id'], att['name'])[0]
        self.db._exec("UPDATE attachments SET last_seen=0 WHERE id=?", (att['id'],))
        before = len(self.stale(att['id']))
        self.assertTrue(await flush([brief['id']]))
        self.assertEqual(len(self.stale(att['id'])), before)

    async def test_stall_reminder_is_not_replayed_after_approval(self):
        row = await self.reviewed()
        self.db._exec('INSERT INTO messages(conv_id,sender,sender_type,body,created_at,'
                      'audience_attachment_id) VALUES(?,?,?,?,?,?)',
                      (self.conv_id, 'system', 'system', 'This task has no hand-off. Call request_review',
                       self.row()['settled_at'] - 1, row['implementer_id']))
        await self.poke(row['implementer_id'])
        self.assertEqual(self.stale(row['implementer_id']), [])

    async def test_acknowledged_report_is_never_woken_again(self):
        await self.reviewed()
        record = reports.get(self.db, self.row()['report_id'])
        reports.acknowledge(self.db, record['id'], 'root', record['revision'])
        self.db._exec('UPDATE line_reports SET notified_at=NULL,notifying_at=NULL WHERE id=?',
                      (record['id'],))
        with patch('partyline.orchestrator_notices.tell', new=AsyncMock()) as wake:
            await report(self.runtime, self.row())
        wake.assert_not_awaited()

    async def test_changes_requested_task_still_delivers_to_its_workers(self):
        row = await self.reviewed('changes')
        self.assertEqual(self.row()['status'], 'implementing')
        await self.poke(row['implementer_id'], row['reviewer_id'])
        self.assertTrue([b for b in self.heard(row['implementer_id']) if 'Changes requested' in b])
        # Still in flight: the unproved review request is not dropped for the reviewer either.
        self.assertGreaterEqual(len([b for b in self.heard(row['reviewer_id']) if 'Review round' in b]), 2)

    async def test_reopen_starts_from_the_reopen_not_from_the_backlog(self):
        row = await self.reviewed()
        implementer, reviewer = row['implementer_id'], row['reviewer_id']
        self.db._exec('INSERT INTO messages(conv_id,sender,sender_type,body,created_at,'
                      'audience_attachment_id) VALUES(?,?,?,?,?,?)',
                      (self.conv_id, 'system', 'system', 'This task has no hand-off. Call request_review',
                       self.row()['settled_at'] - 1, implementer))
        seen = {ident: len(self.stale(ident)) for ident in (implementer, reviewer)}
        await reopen_task(self.runtime, self.captain, self.conv_id, ReopenIn(goal='do the next thing'))
        self.assertIsNone(self.row()['settled_at'])
        await self.poke(implementer, reviewer)
        for ident, count in seen.items():
            self.assertEqual(len(self.stale(ident)), count, ident)
        self.assertTrue([b for b in self.heard(implementer) if 'do the next thing' in b])
        # The new cycle's own request still reaches the reviewer.
        sha = self.commit('second')
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=sha, what='again', where='code'))
        self.assertEqual(len(self.stale(reviewer)), seen[reviewer] + 1)
