"""Captain override verdicts: explicit, auditable, and never silent."""

from fastapi import HTTPException

from partyline import reports
from partyline.auth_guard import Principal
from partyline.orchestrator_contracts import BlockedIn, ReopenIn, ReviewRequestIn, VerdictIn
from partyline.orchestrator_reopen import reopen_task
from partyline.orchestrator_service import request_review, review_verdict
from partyline.orchestrator_stall import blocked
from tests.orchestrator_fixture import TaskFixture


class OverrideFixture(TaskFixture):
    async def asyncSetUp(self):
        await self.create('inspector')
        self.sha = self.commit()
        self.task = await request_review(self.runtime, self.worker, self.conv_id,
                                         ReviewRequestIn(sha=self.sha, what='feature',
                                                         where='code and tests'))
        self.reviewer = self.principal(self.task['reviewer_id'])

    async def override(self, verdict='changes', findings='Fix the edge case'):
        return await review_verdict(self.runtime, self.captain, self.conv_id,
                                    VerdictIn(verdict=verdict, findings=findings, override=True))

    def private_messages(self, ident):
        messages, _ = self.db.message_page(self.conv_id, limit=200)
        return [msg['body'] for msg in messages
                if msg['audience_attachment_id'] == ident and msg['sender_type'] == 'system']


class OverrideVerdictTest(OverrideFixture):
    async def test_override_changes_supersedes_reviewer_and_tells_both(self):
        row = await self.override(findings='Rework the boundary check')
        self.assertEqual(row['status'], 'implementing')
        self.assertEqual(row['round'], 2)
        self.assertEqual(row['findings'], 'Rework the boundary check')
        self.assertEqual(row['previous_findings'], 'Rework the boundary check')
        self.assertEqual(row['overridden_by'], 'captain')
        self.assertTrue(any('Changes requested; round 2: Rework the boundary check' in text
                            for text in self.private_messages(self.worker.attachment_id)))
        notified = [text for text in self.private_messages(self.reviewer.attachment_id)
                    if 'overrode the review' in text]
        self.assertEqual(len(notified), 1, self.private_messages(self.reviewer.attachment_id))
        self.assertIn("Captain @captain overrode the review with a 'changes' verdict: "
                      'Rework the boundary check', notified[0])
        # The superseded reviewer's own verdict can no longer land.
        with self.assertRaises(HTTPException) as refused:
            await review_verdict(self.runtime, self.reviewer, self.conv_id,
                                 VerdictIn(verdict='approve', findings='stale'))
        self.assertEqual(refused.exception.status_code, 409)
        self.assertEqual(self.row()['overridden_by'], 'captain')

    async def test_override_approves_reports_once_and_records_audit_field(self):
        row = await self.override(verdict='approve', findings='Verified at the exact SHA')
        self.assertEqual(row['status'], 'approved')
        self.assertEqual(row['overridden_by'], 'captain')
        notified = [text for text in self.private_messages(self.reviewer.attachment_id)
                    if 'overrode the review' in text]
        self.assertEqual(len(notified), 1)
        self.assertIn("'approve' verdict: Verified at the exact SHA", notified[0])
        records = reports.list_for_parent(self.db, 'root')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['id'], row['report_id'])
        self.assertIsNotNone(records[0]['notified_at'])
        self.assertIn('Verified at the exact SHA', records[0]['body'])
        reopened = await reopen_task(self.runtime, self.captain, self.conv_id,
                                     ReopenIn(goal='Extend the feature'))
        self.assertIsNone(reopened['overridden_by'])


class OverrideRefusalTest(OverrideFixture):
    async def test_plain_call_without_override_keeps_refusing_the_captain(self):
        for actor in (self.captain, self.human, Principal(kind='machine', name='stranger')):
            with self.assertRaises(HTTPException) as refused:
                await review_verdict(self.runtime, actor, self.conv_id,
                                     VerdictIn(verdict='approve', findings='no flag'))
            self.assertEqual(refused.exception.status_code, 403, actor)
        self.assertEqual(self.row()['status'], 'in_review')
        self.assertFalse(any('overrode the review' in text
                              for text in self.private_messages(self.reviewer.attachment_id)))

    async def test_override_refuses_anyone_but_the_root_captain(self):
        self.db.add_attachment('monitor', 'root', 'idle-check', 'fake', ['fake'], self.repo, 'own2')
        monitor = Principal(kind='machine', name='monitor', conv_id='root',
                            attachment_id='monitor', is_lead=False)
        for actor in (self.worker, self.reviewer, self.human, monitor,
                      Principal(kind='machine', name='stranger')):
            with self.assertRaises(HTTPException) as refused:
                await review_verdict(self.runtime, actor, self.conv_id,
                                     VerdictIn(verdict='approve', findings='no flag',
                                               override=True))
            self.assertEqual(refused.exception.status_code, 403, actor)
        self.assertEqual(self.row()['status'], 'in_review')
        self.assertEqual(self.row()['overridden_by'], None)

    async def test_override_refuses_state_machines(self):
        task_line = self.conv_id
        self.conv_id = 'missing'
        with self.assertRaises(HTTPException) as gone:
            await self.override(verdict='changes', findings='no task')
        self.assertEqual(gone.exception.status_code, 404)
        self.conv_id = task_line
        await self.override(verdict='approve', findings='done')
        with self.assertRaises(HTTPException) as settled:
            await self.override(verdict='changes', findings='stale')
        self.assertEqual(settled.exception.status_code, 409)
        reopened = await reopen_task(self.runtime, self.captain, self.conv_id,
                                     ReopenIn(goal='Again'))
        self.assertEqual(reopened['status'], 'implementing')
        with self.assertRaises(HTTPException) as quiet:
            await self.override(verdict='changes', findings='no review in progress')
        self.assertEqual(quiet.exception.status_code, 409)
        self.assertIn('no open review', quiet.exception.detail)

    async def test_override_refuses_tasks_without_a_separate_reviewer(self):
        await self.create('captain')
        sha = self.commit()
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=sha, what='feature', where='code'))
        with self.assertRaises(HTTPException) as refused:
            await review_verdict(self.runtime, self.captain, self.conv_id,
                                 VerdictIn(verdict='approve', findings='mine', override=True))
        self.assertEqual(refused.exception.status_code, 409)
        self.assertIn('separate reviewer', refused.exception.detail)
        # The ordinary captain-policy verdict still needs no override.
        row = await review_verdict(self.runtime, self.captain, self.conv_id,
                                   VerdictIn(verdict='approve', findings='mine'))
        self.assertEqual(row['status'], 'approved')
        self.assertIsNone(row['overridden_by'])


class OverrideAuditTest(OverrideFixture):
    async def test_new_round_and_reviewer_verdict_clear_the_override_marker(self):
        await self.override(findings='First round fix')
        self.assertEqual(self.row()['overridden_by'], 'captain')
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=self.commit('fix'), what='feature',
                                                   where='code'))
        self.assertIsNone(row['overridden_by'])
        self.assertEqual(row['previous_findings'], 'First round fix')
        self.assertEqual(row['status'], 'in_review')
        row = await review_verdict(self.runtime, self.reviewer, self.conv_id,
                                   VerdictIn(verdict='approve', findings='reviewed'))
        self.assertEqual(row['status'], 'approved')
        self.assertIsNone(row['overridden_by'])
        self.assertEqual(row['findings'], 'reviewed')

    async def test_blocked_replaces_the_verdict_and_its_override_marker(self):
        await self.override(findings='Fix it before blocking')
        await blocked(self.runtime, self.worker, self.conv_id, BlockedIn(reason='need creds'))
        row = self.row()
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(row['findings'], 'need creds')
        self.assertIsNone(row['overridden_by'])


class OverrideHttpTest(OverrideFixture):
    """The route, the task row and the tasks listing all carry the override."""

    async def test_route_records_override_and_rows_expose_it(self):
        self.actor = self.captain
        route = f'/api/conversations/{self.conv_id}/review-verdict'
        refused = self.client.post(route, json={'verdict': 'approve', 'findings': 'no flag'})
        self.assertEqual(refused.status_code, 403, refused.text)
        response = self.client.post(route, json={'verdict': 'approve', 'findings': 'verified',
                                                 'override': True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['overridden_by'], 'captain')
        self.assertEqual(response.json()['status'], 'approved')
        detail = self.client.get(f'/api/conversations/{self.conv_id}/task').json()
        self.assertEqual(detail['overridden_by'], 'captain')
        self.actor = self.human
        listed = self.client.get('/api/conversations/root/tasks').json()
        self.assertEqual([row['overridden_by'] for row in listed], ['captain'])
