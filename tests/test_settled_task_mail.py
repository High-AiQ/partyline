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
from partyline.turn_marker import announce_if_interrupted
from tests.orchestrator_fixture import TaskFixture

STALE = ('Review round', 'no hand-off', 'Changes requested', 'continue the task',
         'Implement this task', 'restarted in the middle', 'spawn refused', 'Continuation debrief')


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
        before = len(self.stale(row['implementer_id']))
        await self.poke(row['implementer_id'])
        self.assertEqual(len(self.stale(row['implementer_id'])), before)
        self.assertFalse([b for b in self.heard(row['implementer_id']) if 'no hand-off' in b])

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

    async def interrupted(self, ident):
        self.db._exec('UPDATE attachments SET turn_open=1 WHERE id=?', (ident,))
        self.assertTrue(await announce_if_interrupted(self.runtime, self.db.get_attachment(ident)))

    async def test_initial_assignment_is_not_replayed_after_approval(self):
        row = await self.reviewed()
        implementer = row['implementer_id']
        self.assertTrue([b for b in self.heard(implementer) if 'Implement this task' in b]
                        or not self.batches.get(implementer))
        before = len([b for b in self.heard(implementer) if 'Implement this task' in b])
        await self.poke(implementer)
        await self.poke(implementer)
        self.assertEqual(len([b for b in self.heard(implementer) if 'Implement this task' in b]), before)

    async def test_restart_continuation_after_approval_is_not_delivered(self):
        row = await self.reviewed()
        reviewer = row['reviewer_id']
        await self.interrupted(reviewer)  # a restart notice filed after the task settled
        self.db._exec('UPDATE attachments SET last_seen=0 WHERE id=?', (reviewer,))
        att = self.db.get_attachment(reviewer)
        bodies = [m['body'] for m in addressed_backlog(self.runtime, att)]
        self.assertFalse([b for b in bodies if 'restarted in the middle' in b])
        await self.poke(reviewer)
        self.assertEqual([b for b in self.heard(reviewer) if 'restarted in the middle' in b], [])

    async def test_a_continuation_filed_while_settled_does_not_return_with_the_reopen(self):
        row = await self.reviewed()
        reviewer = row['reviewer_id']
        await self.interrupted(reviewer)
        await reopen_task(self.runtime, self.captain, self.conv_id, ReopenIn(goal='more'))
        await self.poke(reviewer)
        self.assertEqual([b for b in self.heard(reviewer) if 'restarted in the middle' in b], [])

    async def test_a_restart_continuation_of_an_open_task_still_delivers(self):
        await self.create('inspector')
        implementer = self.row()['implementer_id']
        await self.interrupted(implementer)
        await self.poke(implementer)
        self.assertTrue([b for b in self.heard(implementer) if 'restarted in the middle' in b])

    async def test_acknowledged_report_wake_is_dropped_at_delivery(self):
        seen = []

        async def deliver(messages):
            seen.append([m['body'] for m in messages])
            return False
        self.runtime.live['captain'].deliver = deliver
        await self.reviewed()
        wakes = lambda: [b for batch in seen for b in batch if 'needs attention: report' in b]  # noqa: E731
        self.assertEqual(len(wakes()), 1)
        record = reports.get(self.db, self.row()['report_id'])
        reports.acknowledge(self.db, record['id'], 'root', record['revision'])
        await tell(self.runtime, 'captain', 'unrelated word for the captain')
        self.assertEqual(len(wakes()), 1)
        self.assertTrue([b for b in seen[-1] if 'unrelated word' in b])

    async def test_held_flush_drops_the_assignment_and_acknowledged_report_wakes(self):
        row = await self.reviewed()
        record = reports.get(self.db, self.row()['report_id'])
        reports.acknowledge(self.db, record['id'], 'root', record['revision'])
        def find(conv, text):
            return self.db.messages_by_ids(conv, [self.db._exec(
                'SELECT MAX(id) FROM messages WHERE conv_id=? AND body LIKE ?',
                (conv, f'%{text}%')).fetchone()[0]])[0]
        assignment = find(self.conv_id, 'Implement this task')
        wake = find(self.row()['root_id'], 'needs attention: report')
        for ident, message in ((row['implementer_id'], assignment), ('captain', wake)):
            att = self.db.get_attachment(ident)
            flush = self.runtime.held_wake_hooks(att['conv_id'], att['id'], att['name'])[0]
            before = sum(len(batch) for batch in self.batches.get(ident, []))
            self.assertTrue(await flush([message['id']]))
            self.assertEqual(sum(len(batch) for batch in self.batches.get(ident, [])), before, ident)

    async def cycle(self, goal):
        """Reopen the approved task, review a new commit and approve it again."""
        await reopen_task(self.runtime, self.captain, self.conv_id, ReopenIn(goal=goal))
        sha = self.commit(goal)
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=sha, what=goal, where='code'))
        await review_verdict(self.runtime, self.reviewer, self.conv_id,
                             VerdictIn(verdict='approve', findings='fine', sha=sha))

    async def test_a_reopened_assignment_is_not_replayed_after_the_next_approval(self):
        row = await self.reviewed()
        implementer = row['implementer_id']

        def reopens(goal):
            return len([b for b in self.heard(implementer) if 'New work on this task' in b and goal in b])
        await self.cycle('second feature')
        await self.poke(implementer)
        await self.poke(implementer)
        self.assertEqual(reopens('second feature'), 1)  # delivered when it was reopened, never again
        await self.cycle('third feature')
        await self.poke(implementer)
        self.assertEqual((reopens('second feature'), reopens('third feature')), (1, 1))

    async def test_the_real_restart_coordinator_does_not_wake_an_approved_reviewer(self):
        from partyline.reattach import ReattachCoordinator, ResumedAttachment
        from tests.test_reattach import ReadyAdapter
        row = await self.reviewed()
        reviewer = row['reviewer_id']
        self.runtime.live.pop(reviewer, None)
        self.db._exec("UPDATE attachments SET status='exited',turn_open=1 WHERE id=?", (reviewer,))
        plan = self.db.save_restart_plan('root', [reviewer], '')
        resumed = {}

        async def resume(ident, pending):
            resumed['pending'] = [m['body'] for m in pending]
            att = self.db.get_attachment(ident)
            adapter = ReadyAdapter([], 'reviewer')
            adapter.att = {'runtime_owner': att['runtime_owner']}
            self.db.set_attachment_status(ident, 'running', att['runtime_owner'])
            self.runtime.live[ident] = adapter
            resumed['adapter'] = adapter
            return ResumedAttachment(adapter, False)
        await ReattachCoordinator(self.runtime, resume).run(plan, None)
        woken = [b for b in resumed['pending']
                 if 'Continuation debrief' in b or 'restarted in the middle' in b or 'Review round' in b]
        self.assertEqual(woken, [])
        # The next live wake must not carry the persisted restart debrief either.
        await tell(self.runtime, reviewer, 'unrelated word after the restart')
        pasted = [m['body'] for batch in resumed['adapter'].deliveries for m in batch]
        self.assertTrue([b for b in pasted if 'unrelated word after the restart' in b], pasted)
        self.assertEqual([b for b in pasted if 'Continuation debrief' in b or 'restarted in the middle' in b],
                         [])

    async def test_the_real_restart_coordinator_still_wakes_an_open_review(self):
        from partyline.reattach import ReattachCoordinator, ResumedAttachment
        from tests.test_reattach import ReadyAdapter
        await self.create('inspector')
        sha = self.commit()
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=sha, what='fix', where='code'))
        reviewer = row['reviewer_id']
        self.runtime.live.pop(reviewer, None)
        self.db._exec("UPDATE attachments SET status='exited',turn_open=1 WHERE id=?", (reviewer,))
        plan = self.db.save_restart_plan('root', [reviewer], '')
        resumed = {}

        async def resume(ident, pending):
            resumed['pending'] = [m['body'] for m in pending]
            adapter = ReadyAdapter([], 'reviewer')
            self.runtime.live[ident] = adapter
            return ResumedAttachment(adapter, False)
        await ReattachCoordinator(self.runtime, resume).run(plan, None)
        self.assertTrue([b for b in resumed['pending'] if 'Continuation debrief' in b])
        self.assertTrue([b for b in resumed['pending'] if 'restarted in the middle' in b])

    async def test_a_recovered_admission_failure_is_not_replayed_after_approval(self):
        from fastapi import HTTPException
        from partyline import orchestrator_service
        await self.create('inspector')
        sha = self.commit()
        real = orchestrator_service.ensure_reviewer
        calls = []

        async def flaky(runtime, row):
            calls.append(1)
            if len(calls) == 1:
                raise HTTPException(503, 'capacity full')
            return await real(runtime, row)
        with patch.object(orchestrator_service, 'ensure_reviewer', flaky):
            with self.assertRaises(HTTPException):
                await request_review(self.runtime, self.worker, self.conv_id,
                                     ReviewRequestIn(sha=sha, what='fix', where='code'))
            row = await request_review(self.runtime, self.worker, self.conv_id,
                                       ReviewRequestIn(sha=sha, what='fix', where='code'))
        reviewer = self.principal(row['reviewer_id'])
        await review_verdict(self.runtime, reviewer, self.conv_id,
                             VerdictIn(verdict='approve', findings='fine', sha=sha))
        implementer = row['implementer_id']
        refused = lambda: [b for b in self.heard(implementer) if 'spawn refused' in b]  # noqa: E731
        before = len(refused())
        await self.poke(implementer)
        await self.poke(implementer)
        self.assertEqual(len(refused()), before)
