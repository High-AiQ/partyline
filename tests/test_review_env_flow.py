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

    async def test_failed_setup_does_not_prevent_other_reviews_refreshing(self):
        first = await self.review()
        second = await self.review()
        body = ReviewEnvOperation(operation='set', repository=self.repo, setup='prepare', test='run tests')
        from fastapi import HTTPException
        from partyline.review_install_sandbox import DependencyError
        self.runtime.post_message = AsyncMock()
        with patch('partyline.review_env_operations.provision',
                   side_effect=[DependencyError('first failed'), None]) as provision, \
                patch('partyline.review_env_operations.tell', new_callable=AsyncMock) as tell:
            with self.assertRaises(HTTPException) as error:
                await operate(self.runtime, self.captain, 'root', body)
        self.assertIn('first failed', error.exception.detail)
        self.assertEqual(provision.call_count, 2)
        messages = {call.args[1]: call.args[2] for call in tell.await_args_list}
        self.assertIn('first failed', messages[first['reviewer_id']])
        self.assertIn('run tests', messages[second['reviewer_id']])
        self.assertEqual(self.row()['round'], second['round'])
        with patch('partyline.review_env_operations.provision',
                   side_effect=[DependencyError('first failed'), DependencyError('second failed')]), \
                patch('partyline.review_env_operations.tell', new_callable=AsyncMock):
            with self.assertRaises(HTTPException) as both:
                await operate(self.runtime, self.captain, 'root', body)
        self.assertIn('first failed', both.exception.detail)
        self.assertIn('second failed', both.exception.detail)

    async def test_round_brief_and_environment_update_scope_configured_suite_commands(self):
        await self.create()
        self.db._exec('INSERT INTO review_environments VALUES(?,?,?,?,?,?)',
                      (self.repo, '.', '', 'npm test', 'person', 1))
        cwd = self.db.get_conversation(self.conv_id)['cwd']
        Path(cwd, 'changed.txt').write_text('change')
        git(cwd, 'add', 'changed.txt')
        with patch('partyline.task_review_checkout.provision'):
            row = await request_review(self.runtime, self.worker, self.conv_id,
                                      ReviewRequestIn(sha=self.commit(), what='change', where='code'))
        brief = next(message['body'] for message in self.db.list_messages(self.conv_id)
                     if message['audience_attachment_id'] == row['reviewer_id']
                     and 'Review round' in message['body'])
        self.runtime.post_message = AsyncMock()
        with patch('partyline.review_env_operations.provision'), patch(
                'partyline.review_env_operations.tell', new_callable=AsyncMock) as tell:
            await operate(self.runtime, self.captain, 'root', ReviewEnvOperation(
                operation='set', repository=self.repo, test='pytest'))
        updated = tell.await_args.args[2]
        self.assertIn('npm test', brief)
        self.assertIn('pytest', updated)
        for notice in [brief, updated]:
            self.assertIn('scope the configured test command', notice)
            self.assertIn('only tests reaching changed code', notice)
            self.assertIn('Never run full suites, e2e suites or whole-suite coverage', notice)
            self.assertIn('Call env_gap only when affected tests cannot run', notice)
            self.assertIn('List the test commands run and their results', notice)
