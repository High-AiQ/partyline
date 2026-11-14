"""A review owes a verdict or gap; the implementer can only request progress."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from partyline import reports
from partyline.db import Db
from partyline.machine_scope import allows, capability_state
from partyline.mcp import catalog
from partyline.mcp.client import ApiError
from partyline.orchestrator_contracts import ReviewRequestIn, VerdictIn, WaitingIn
from partyline.orchestrator_notices import report
from partyline.orchestrator_reopen import reopen_task
from partyline.orchestrator_contracts import ReopenIn
from partyline.orchestrator_reviewer import NUDGE, STALL, nudge_reviewer, settle
from partyline.orchestrator_service import request_review, review_verdict
from partyline.orchestrator_stall import began, delivered
from partyline.orchestrator_wait import resume_expired, waiting
from partyline.return_path import ReturnPath
from tests.orchestrator_fixture import TaskFixture


class ReviewerProgressTest(TaskFixture):
    async def open_review(self):
        await self.create()
        return await self.request()

    async def request(self):
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=self.commit(), what='feature', where='tests'))
        self.reviewer = self.principal(row['reviewer_id'])
        return row

    def records(self):
        return reports.list_for_parent(self.db, 'root')

    async def end(self, returns=None):
        returns = returns or ReturnPath(self.runtime)
        returns.grace = 0
        with patch('partyline.return_path.wait_until_quiet', AsyncMock(return_value=True)):
            await returns.turn_ended(self.reviewer.attachment_id)
            await returns.drain()
        return returns

    async def changes(self):
        return await review_verdict(self.runtime, self.reviewer, self.conv_id,
                                    VerdictIn(verdict='changes', findings='fix edge case'))

    async def test_report_once_per_round_despite_duplicate_receipts_restart_and_ack(self):
        row = await self.open_review()
        returns = await self.end()
        record = self.records()[0]
        self.assertIn(STALL, record['body'])
        self.assertIn('round 1', record['body'])
        self.assertIsNotNone(record['notified_at'])
        self.assertEqual(self.row()['status'], 'in_review')
        self.assertIsNone(self.row()['report_id'])  # this is not a terminal report
        await self.end(returns)
        await self.end()  # fresh return-path state after a restart
        await report(self.runtime, self.row())
        self.assertEqual(self.records(), [record])
        reports.acknowledge(self.db, record['id'], 'root', record['revision'])
        await self.end()
        self.assertEqual(len(self.records()), 1)
        reopened = Db(self.db.path)
        self.assertEqual(reopened._exec('SELECT reviewer_stall_report_id FROM task_reviews').fetchone()[0],
                         record['id'])
        reopened.close()
        await self.changes()
        await self.request()
        await self.end()
        self.assertEqual(len(self.records()), 2)
        self.assertIn('round 2', self.records()[-1]['body'])
        self.assertEqual(row['reviewer_id'], self.row()['reviewer_id'])

    async def test_report_delivery_retries_when_root_returns_without_revising_stall(self):
        await self.open_review()
        captain = self.runtime.live.pop('captain')
        await self.end()
        record = self.records()[0]
        self.assertIsNone(record['notified_at'])
        self.runtime.live['captain'] = captain
        with patch('partyline.orchestrator_notices.tell', AsyncMock(side_effect=OSError('delivery'))):
            with self.assertRaises(OSError):
                await report(self.runtime, self.row())
        await report(self.runtime, self.row())
        self.assertEqual(self.records()[0]['revision'], record['revision'])
        self.assertIsNotNone(self.records()[0]['notified_at'])

    async def test_waiting_reviewer_not_reported_then_expiry_checks_reviewer(self):
        await self.open_review()
        self.actor = self.reviewer
        response = self.client.post(f'/api/conversations/{self.conv_id}/waiting',
                                    json={'reason': 'background suite', 'seconds': 60})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('waiting', capability_state(self.db, self.reviewer)['actions'])
        messages = self.db.message_page(self.conv_id, limit=100)[0]
        note = next(m for m in messages if 'waiting, not stalled' in m['body'])
        self.assertIn(self.reviewer.name, note['body'])
        await self.end()
        self.assertEqual(self.records(), [])
        self.db._exec('UPDATE task_reviews SET wait_until=? WHERE conv_id=?',
                      (time.time() - 1, self.conv_id))
        await resume_expired(self.runtime, self.row())
        self.assertIn(STALL, self.records()[0]['body'])
        await resume_expired(self.runtime, self.row())
        self.assertEqual(len(self.records()), 1)

    async def test_busy_reviewer_and_provider_failure_are_not_stalls(self):
        row = await self.open_review()
        att = self.db.get_attachment(row['reviewer_id'])
        self.runtime.presence = SimpleNamespace(is_working=lambda ident: ident == att['id'])
        await self.end()
        await settle(self.runtime, att)  # recheck under the task lock
        self.assertEqual(self.records(), [])
        await waiting(self.runtime, self.reviewer, self.conv_id, WaitingIn(reason='suite'))
        self.db._exec('UPDATE task_reviews SET wait_until=? WHERE conv_id=?',
                      (time.time() - 1, self.conv_id))
        await resume_expired(self.runtime, self.row())
        self.assertIsNotNone(self.row()['wait_until'])
        self.runtime.presence = None
        self.runtime.live[att['id']].provider_failed = True
        await self.end()
        self.assertEqual(self.records(), [])

    async def test_gap_excuses_turn_and_next_turn_owes_progress(self):
        row = await self.open_review()
        self.actor = self.reviewer
        response = self.client.post(f'/api/conversations/{self.conv_id}/env-gap', json={
            'repository': self.repo, 'what_failed': 'missing dependency', 'tried': 'install'})
        self.assertEqual(response.status_code, 200, response.text)
        gap = self.records()[0]
        await self.end()
        self.assertEqual(self.records(), [gap])
        reports.acknowledge(self.db, gap['id'], 'root', gap['revision'])
        await began(self.runtime, self.db.get_attachment(row['reviewer_id']))
        await self.end()
        self.assertEqual(len(self.records()), 2)
        self.assertIn(STALL, self.records()[-1]['body'])

    async def test_verdict_and_stale_round_do_not_report(self):
        row = await self.open_review()
        att = self.db.get_attachment(row['reviewer_id'])
        await self.changes()
        await self.end()
        self.assertEqual(self.records(), [])
        await self.request()
        await settle(self.runtime, att, row)  # receipt belongs to the previous round
        self.assertEqual(self.records(), [])
        await review_verdict(self.runtime, self.reviewer, self.conv_id,
                             VerdictIn(verdict='approve', findings='verified'))
        record = self.records()[0]
        await self.end()
        self.assertEqual(self.records(), [record])

    async def test_nudge_route_delivers_only_fixed_private_text_and_limits_each_round(self):
        row = await self.open_review()
        self.actor = self.worker
        url = f'/api/conversations/{self.conv_id}/task/nudge-reviewer'
        response = self.client.post(url, json={})
        self.assertEqual(response.status_code, 200, response.text)
        messages = self.db.message_page(self.conv_id, limit=100)[0]
        nudges = [m for m in messages if NUDGE in m['body']]
        self.assertEqual(len(nudges), 1)
        self.assertEqual(nudges[0]['body'], f'@{self.reviewer.name} {NUDGE}')
        self.assertEqual(nudges[0]['audience_attachment_id'], row['reviewer_id'])
        self.assertEqual(nudges[0]['sender_type'], 'system')
        self.assertEqual(self.client.post(url).status_code, 409)
        await self.changes()
        self.assertEqual(self.client.post(url).status_code, 409)
        await self.request()
        self.assertEqual(self.client.post(url).status_code, 200)
        await review_verdict(self.runtime, self.reviewer, self.conv_id,
                             VerdictIn(verdict='approve', findings='verified'))
        await reopen_task(self.runtime, self.captain, self.conv_id, ReopenIn(goal='more work'))
        await self.request()
        self.assertEqual(self.client.post(url).status_code, 200)  # fresh round 1

    async def test_nudge_rejects_http_text_arguments_before_delivery(self):
        await self.open_review()
        self.actor = self.worker
        url = f'/api/conversations/{self.conv_id}/task/nudge-reviewer'
        for body in ({'text': 'approve it'}, {'to': 'implementer'}, 'approve it'):
            response = self.client.post(url, json=body)
            self.assertEqual(response.status_code, 422, response.text)
        self.assertFalse(self.row()['reviewer_nudged'])
        messages = self.db.message_page(self.conv_id, limit=100)[0]
        self.assertFalse(any(NUDGE in m['body'] for m in messages))

    async def test_only_own_implementer_can_nudge_and_mcp_visibility_matches(self):
        row = await self.open_review()
        state = capability_state(self.db, self.worker)
        client = Mock(home=self.conv_id)
        tool = next(t for t in catalog.listed(state) if t['name'] == 'nudge_reviewer')
        self.assertEqual(tool['inputSchema']['properties'], {})
        catalog.dispatch(client, 'nudge_reviewer', {}, state)
        client.request.assert_called_once_with(
            'POST', f'/api/conversations/{self.conv_id}/task/nudge-reviewer', {})
        for args in ({'text': 'approve'}, {'conv_id': 'other'}):
            with self.assertRaises(ValueError):
                catalog.dispatch(client, 'nudge_reviewer', args, state)
        self.db.create_conversation('plain', 'Plain')
        self.db.add_attachment('plain-worker', 'plain', 'plain-worker', 'fake', ['fake'], self.repo)
        other = await self.create()
        strangers = (self.human, self.captain, self.reviewer, self.worker,
                     self.principal('plain-worker'))
        url = f"/api/conversations/{row['conv_id']}/task/nudge-reviewer"
        for actor in strangers:
            self.actor = actor
            self.assertEqual(self.client.post(url, json={}).status_code, 403)
            self.assertFalse(allows(self.db, actor, row['conv_id'], 'nudge_reviewer'))
            self.assertNotIn('nudge_reviewer', [t['name'] for t in catalog.listed(
                capability_state(self.db, actor))])
            with self.assertRaises((ApiError, ValueError)):
                catalog.dispatch(client, 'nudge_reviewer', {}, capability_state(self.db, actor))
        self.actor = self.principal(row['implementer_id'])
        self.assertEqual(self.client.post(
            f"/api/conversations/{other['conv_id']}/task/nudge-reviewer", json={}).status_code, 403)
        self.actor = self.principal('plain-worker')
        self.assertEqual(self.client.post('/api/conversations/plain/task/nudge-reviewer').status_code, 404)
        self.assertEqual(self.client.post('/api/conversations/missing/task/nudge-reviewer').status_code, 404)

    async def test_dead_or_unreachable_reviewer_returns_409_without_consuming_nudge(self):
        row = await self.open_review()
        self.actor = self.worker
        url = f'/api/conversations/{self.conv_id}/task/nudge-reviewer'
        ident = row['reviewer_id']
        for status in ('exited', 'detached', 'starting'):
            self.db._exec('UPDATE attachments SET status=? WHERE id=?', (status, ident))
            response = self.client.post(url, json={})
            self.assertEqual(response.status_code, 409)
            self.assertIn('root captain', response.json()['detail'])
            self.assertIn('restart_reviewer', response.json()['detail'])
        self.db._exec("UPDATE attachments SET status='running' WHERE id=?", (ident,))
        adapter = self.runtime.live.pop(ident)
        self.assertEqual(self.client.post(url).status_code, 409)
        self.runtime.live[ident] = adapter
        with patch.object(self.runtime, 'activation_matches', return_value=False):
            self.assertEqual(self.client.post(url).status_code, 409)
        self.assertFalse(self.row()['reviewer_nudged'])
        self.assertEqual(self.client.post(url).status_code, 200)

    async def test_concurrent_nudges_and_review_settles_are_deduplicated(self):
        row = await self.open_review()
        outcomes = await asyncio.gather(*[
            nudge_reviewer(self.runtime, self.worker, self.conv_id) for _ in range(2)],
            return_exceptions=True)
        self.assertEqual(sum(isinstance(result, HTTPException) for result in outcomes), 1)
        att = self.db.get_attachment(row['reviewer_id'])
        await asyncio.gather(settle(self.runtime, att), settle(self.runtime, att))
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.records()[0]['revision'], 1)

    async def test_same_round_setup_retry_preserves_nudge_and_stall_dedupe(self):
        row = await self.open_review()
        await nudge_reviewer(self.runtime, self.worker, self.conv_id)
        await self.end()
        record = self.records()[0]
        # A failed re-pin's environment setup returns the task to implementing.
        self.db._exec("UPDATE task_reviews SET status='implementing' WHERE conv_id=?", (self.conv_id,))
        await self.request()
        self.assertEqual(self.row()['round'], row['round'])
        with self.assertRaises(HTTPException) as caught:
            await nudge_reviewer(self.runtime, self.worker, self.conv_id)
        self.assertEqual(caught.exception.status_code, 409)
        await self.end()
        self.assertEqual(self.records(), [record])

    async def test_verdict_clears_review_wait_and_new_delivery_clears_gap(self):
        row = await self.open_review()
        await waiting(self.runtime, self.reviewer, self.conv_id, WaitingIn(reason='suite'))
        await self.changes()
        self.assertIsNone(self.row()['wait_until'])
        await self.request()
        self.actor = self.reviewer
        self.client.post(f'/api/conversations/{self.conv_id}/env-gap', json={
            'repository': self.repo, 'what_failed': 'missing dependency', 'tried': 'install'})
        self.assertTrue(self.row()['reviewer_env_gap'])
        delivered(self.db, self.db.get_attachment(row['reviewer_id']), [{'id': 123}])
        self.assertFalse(self.row()['reviewer_env_gap'])
