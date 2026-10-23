"""Orchestrator task policies, admission, review identities and retention."""

import asyncio
import os
import sqlite3
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from partyline import reports
from partyline.auth_guard import Principal
from partyline.hierarchy import create_child_conversation
from partyline.machine_scope import allows, capability_state
from partyline.orchestrator_contracts import ReviewRequestIn, TaskIn, VerdictIn
from partyline.orchestrator_notices import report, peer
from partyline.orchestrator_service import create_task, request_review, review_verdict
from partyline.orchestrator_store import require_root, require_task, tasks, validate_policy
from partyline.restart_scope import select_attachment_ids
from tests.orchestrator_fixture import TaskFixture, git


class WorkflowTest(TaskFixture):
    async def request(self, sha=None):
        return await request_review(self.runtime, self.worker, self.conv_id,
                                    ReviewRequestIn(sha=sha, what='feature', where='code and tests'))

    async def test_reviewer_changes_then_approves_same_identity_and_exact_sha(self):
        row = await self.create()
        sha = self.commit()
        row = await self.request(sha)
        reviewer = self.principal(row['reviewer_id'])
        self.assertNotEqual(reviewer.attachment_id, self.worker.attachment_id)
        self.assertEqual(row['status'], 'in_review')
        self.assertEqual(row['round'], 1)
        self.assertEqual(git(row['review_worktree'], 'rev-parse', 'HEAD'), sha)
        self.assertEqual(self.db.get_attachment(reviewer.attachment_id)['cwd'], row['review_worktree'])
        self.assertEqual(tasks(self.db, 'root'), [row])
        self.assertEqual(reports.list_for_parent(self.db, 'root'), [])
        self.assertEqual(capability_state(self.db, reviewer)['role'], 'reviewer')
        self.assertTrue(allows(self.db, reviewer, self.conv_id, 'review_verdict'))
        self.assertFalse(allows(self.db, self.worker, self.conv_id, 'review_verdict'))
        selected = select_attachment_ids(self.db, self.runtime.live, lambda _: True, ['root', self.conv_id])
        self.assertIn(reviewer.attachment_id, selected)
        duplicate = await self.request(sha)
        self.assertEqual(duplicate, row)
        changed = await review_verdict(self.runtime, reviewer, self.conv_id,
                                       VerdictIn(verdict='changes', findings='Fix the edge case'))
        self.assertEqual(changed['round'], 2)
        self.assertEqual(changed['status'], 'implementing')
        new_sha = self.commit('fix')
        row = await self.request(new_sha)
        self.assertEqual(row['reviewer_id'], reviewer.attachment_id)
        self.assertEqual(row['sha'], new_sha)
        self.assertEqual(row['round'], 2)
        approved = await review_verdict(self.runtime, reviewer, self.conv_id,
                                        VerdictIn(verdict='approve', findings='Verified at SHA'))
        self.assertEqual(approved['status'], 'approved')
        records = reports.list_for_parent(self.db, 'root')
        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0]['notified_at'])
        await report(self.runtime, approved)
        await self.request(new_sha)
        self.assertEqual(len(reports.list_for_parent(self.db, 'root')), 1)
        with self.assertRaises(HTTPException):
            await review_verdict(self.runtime, reviewer, self.conv_id,
                                 VerdictIn(verdict='changes', findings='stale verdict'))
        self.assertIsNone(peer(self.db, self.db.get_attachment(self.worker.attachment_id)))

    async def test_none_and_captain_policies_report_once_without_reviewer_spawn(self):
        for policy in ('none', 'captain'):
            with self.subTest(policy=policy):
                await self.create(policy)
                sha = self.commit()
                with patch('partyline.orchestrator_service.ensure_reviewer') as spawn:
                    row = await self.request(sha)
                    spawn.assert_not_called()
                self.assertEqual(row['status'], 'done' if policy == 'none' else 'in_review')
                self.assertIsNone(row['reviewer_id'])
                self.assertEqual(len([r for r in reports.list_for_parent(self.db, 'root')
                                      if r['child_conv_id'] == self.conv_id]), 1)
                if policy == 'captain':
                    row = await review_verdict(self.runtime, self.captain, self.conv_id,
                                               VerdictIn(verdict='changes', findings='missing test'))
                    self.assertEqual(row['status'], 'implementing')
                    await self.request(sha)
                    await review_verdict(self.runtime, self.captain, self.conv_id,
                                         VerdictIn(verdict='approve', findings='fixed'))
                    self.assertEqual(self.row()['status'], 'approved')

    async def test_admission_refusal_tells_both_and_retries_same_reserved_reviewer(self):
        await self.create()
        self.commit()
        with patch('partyline.resource_budget.reject_if_full', side_effect=HTTPException(409, 'budget full')):
            with self.assertRaises(HTTPException):
                await self.request()
        failed = self.row()
        self.assertEqual(failed['status'], 'implementing')
        reserved = failed['reviewer_id']
        self.assertIsNotNone(reserved)
        self.assertIsNone(self.db.get_attachment(reserved))
        for line in ('root', self.conv_id):
            messages, _ = self.db.message_page(line, limit=100)
            self.assertTrue(any('budget full' in msg['body'] for msg in messages))
        row = await self.request()
        self.assertEqual(row['reviewer_id'], reserved)
        self.assertEqual(row['status'], 'in_review')
        self.assertEqual(reports.list_for_parent(self.db, 'root'), [])

    async def test_concurrent_requests_spawn_one_reviewer_and_one_round(self):
        await self.create()
        sha = self.commit()
        results = await asyncio.gather(self.request(sha), self.request(sha))
        self.assertEqual(results[0]['reviewer_id'], results[1]['reviewer_id'])
        self.assertEqual(len(self.db.list_attachments(self.conv_id)), 2)
        self.assertEqual(self.row()['round'], 1)

    async def test_server_authorization_and_staffing_guard(self):
        row = await self.create()
        for actor in (self.human, self.captain, Principal(kind='machine', name='stranger')):
            with self.assertRaises(HTTPException):
                require_task(self.db, actor, self.conv_id)
        with self.assertRaises(HTTPException):
            require_task(self.db, self.worker, 'missing')
        for action in ('attach', 'appoint_lead', 'create_child', 'notify', 'report'):
            self.assertFalse(allows(self.db, self.captain, self.conv_id, action), action)
            self.assertFalse(allows(self.db, self.worker, self.conv_id, action), action)
        self.assertTrue(allows(self.db, self.captain, self.conv_id, 'archive'))
        self.assertFalse(allows(self.db, self.worker, self.conv_id, 'archive'))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.add_attachment('extra', self.conv_id, 'extra', 'fake', ['fake'], self.repo)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db._exec('UPDATE attachments SET is_lead=1 WHERE id=?', (row['implementer_id'],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db._exec("UPDATE conversations SET parent_id=NULL WHERE id=?", (self.conv_id,))
        with self.assertRaises(HTTPException):
            await create_task(self.runtime, self.worker, self.conv_id, TaskIn(
                name='nested', goal='no', implementer='builder'))
        with self.assertRaises(HTTPException):
            validate_policy(self.db, 'unknown')
        with self.assertRaises(HTTPException):
            require_root(self.db, self.worker, self.conv_id)
        self.assertTrue(allows(self.db, self.captain, 'root', 'create_task'))

    async def test_invalid_sha_does_not_open_review_or_spawn(self):
        await self.create()
        with self.assertRaises(HTTPException):
            await self.request('0' * 40)
        self.assertEqual(self.row()['status'], 'implementing')
        self.assertEqual(len(self.db.list_attachments(self.conv_id)), 1)

    async def test_report_delivery_retries_without_duplicate_or_ack_rewake(self):
        await self.create('none')
        self.commit()
        self.runtime.live.pop('captain')
        row = await self.request()
        record = reports.get(self.db, row['report_id'])
        self.assertIsNone(record['notified_at'])
        self.runtime.live['captain'] = type('Adapter', (), {'att': {'runtime_owner': 'owner'}})()
        with patch('partyline.orchestrator_notices.tell', new=AsyncMock(side_effect=OSError('delivery'))):
            with self.assertRaises(OSError):
                await report(self.runtime, row)
        await report(self.runtime, row)
        record = reports.get(self.db, row['report_id'])
        self.assertIsNotNone(record['notified_at'])
        reports.acknowledge(self.db, record['id'], 'root', record['revision'])
        await report(self.runtime, row)
        self.assertEqual(len(reports.list_for_parent(self.db, 'root')), 1)

    async def test_mode_is_root_only_and_idempotent_migrations(self):
        create_child_conversation(self.db, 'root', 'child', 'Child')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db._exec("UPDATE conversations SET captain_mode='orchestrator' WHERE id='child'")
        from partyline.db import Db
        reopened = Db(self.db.path)
        reopened.close()
        self.assertEqual(self.db.get_conversation('root')['default_review_policy'], 'captain')
        self.assertTrue(os.path.isdir(self.repo))

    async def test_failed_implementer_first_launch_retries_original_identity(self):
        original_start = self.start

        async def fail(att, **kwargs):
            self.db.set_attachment_status(att['id'], 'exited', att['runtime_owner'])
            raise HTTPException(409, 'PTY unavailable')

        assignment = TaskIn(name='retry', goal='feature', implementer='builder')
        with patch('partyline.server._start_attachment', fail):
            with self.assertRaises(HTTPException):
                await create_task(self.runtime, self.captain, 'root', assignment)
        pending = tasks(self.db, 'root')[0]
        with patch('partyline.server._start_attachment', original_start):
            result = await create_task(self.runtime, self.captain, 'root', assignment)
        self.assertEqual(result['implementer_id'], pending['implementer_id'])
        self.assertEqual(len(tasks(self.db, 'root')), 1)

    async def test_root_monitors_are_not_implementers_so_create_task_still_splits(self):
        """A person's reminder script on the root used to make every create_task a 403."""
        self.db.add_attachment('monitor', 'root', 'idle-check', 'fake', ['fake'], self.repo, 'own2')
        self.db._exec("UPDATE attachments SET status='running' WHERE id='monitor'")
        row = await self.create()
        self.assertEqual(row['root_id'], 'root')

    async def test_stopped_reviewer_resumes_same_cli_session_and_guard_refuses_self_review(self):
        from partyline.orchestrator_staff import ensure_reviewer, restart
        await self.create()
        row = await self.request()
        ident = row['reviewer_id']
        self.db.set_attachment_status(ident, 'detached', self.db.get_attachment(ident)['runtime_owner'])
        self.db._exec("UPDATE attachments SET cli_session='existing-session' WHERE id=?", (ident,))
        with patch('partyline.server._resume_adapter', AsyncMock(side_effect=self.resume)) as resumed:
            await ensure_reviewer(self.runtime, row)
            resumed.assert_awaited_once_with(ident)
        invalid = {**row, 'reviewer_id': row['implementer_id']}
        with self.assertRaises(HTTPException):
            await ensure_reviewer(self.runtime, invalid)
        with patch('partyline.orchestrator_staff.claim_resume', AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException):
                await restart(self.runtime, self.db.get_attachment(self.worker.attachment_id))
