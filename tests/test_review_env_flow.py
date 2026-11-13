"""Reviewers report environment gaps and captains resolve them in place."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from partyline import reports
from partyline.orchestrator_contracts import ReviewRequestIn
from partyline.orchestrator_service import request_review
from partyline.review_env_operations import ReviewEnvOperation, operate
from tests.orchestrator_fixture import TaskFixture, git


class ReviewEnvFlowTest(TaskFixture):
    async def review(self):
        await self.create()
        cwd = self.db.get_conversation(self.conv_id)['cwd']
        Path(cwd, 'changed.txt').write_text('change')
        git(cwd, 'add', 'changed.txt')
        sha = self.commit()
        return await request_review(self.runtime, self.worker, self.conv_id,
                                    ReviewRequestIn(sha=sha, what='change', where='code'))

    async def test_gap_and_captain_set_rewake_in_same_round(self):
        row = await self.review()
        reviewer = self.principal(row['reviewer_id'])
        from partyline.machine_scope import allows
        self.assertTrue(allows(self.db, reviewer, self.conv_id, 'env_gap'))
        self.assertFalse(allows(self.db, self.worker, self.conv_id, 'env_gap'))
        self.actor = reviewer
        gap = self.client.post(f'/api/conversations/{self.conv_id}/env-gap', json={
            'repository': self.repo, 'what_failed': 'tests unavailable', 'tried': 'run tests'})
        self.assertEqual(gap.status_code, 200)
        self.assertTrue(any('tests unavailable' in r['body']
                            for r in reports.list_for_parent(self.db, 'root')))
        body = ReviewEnvOperation(operation='set', repository=self.repo,
                                  setup='prepare', test='run tests')
        self.runtime.post_message = AsyncMock()
        with patch('partyline.review_env_operations.provision') as provision, \
                patch('partyline.review_env_operations.tell', new_callable=AsyncMock) as tell:
            await operate(self.runtime, self.captain, 'root', body)
        self.assertEqual(provision.call_count, 1)
        self.assertIn('run tests', tell.await_args.args[2])
        self.assertEqual(self.row()['round'], row['round'])
        self.assertEqual(self.row()['status'], 'in_review')
        self.assertIn('set by captain', self.runtime.post_message.await_args.args[3])
        with self.assertRaisesRegex(Exception, '403'):
            await operate(self.runtime, reviewer, 'root', body)

    async def test_brief_lists_test_command_and_failure_precedes_wake(self):
        await self.create()
        cwd = self.db.get_conversation(self.conv_id)['cwd']
        Path(cwd, 'changed.txt').write_text('change')
        git(cwd, 'add', 'changed.txt')
        sha = self.commit()
        self.db._exec('INSERT INTO review_environments VALUES(?,?,?,?,?,?)',
                      (self.repo, '.', 'prepare', 'run tests', 'person', 1))
        from partyline.review_install_sandbox import DependencyError
        from fastapi import HTTPException
        request = ReviewRequestIn(sha=sha, what='change', where='code')
        with patch('partyline.task_review_checkout.provision', side_effect=DependencyError('setup failed')):
            with self.assertRaises(HTTPException):
                await request_review(self.runtime, self.worker, self.conv_id, request)
        self.assertIsNone(self.row()['reviewer_id'])
        self.assertTrue(any('setup failed' in r['body'] for r in reports.list_for_parent(self.db, 'root')))
        with patch('partyline.task_review_checkout.provision'):
            row = await request_review(self.runtime, self.worker, self.conv_id, request)
        messages = self.db.list_messages(self.conv_id)
        self.assertTrue(any('run tests' in m['body'] and m['audience_attachment_id'] == row['reviewer_id']
                            for m in messages))
