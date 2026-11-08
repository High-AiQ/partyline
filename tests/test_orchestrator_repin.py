"""Open reviews follow new commits without accepting stale verdicts."""

from unittest.mock import patch

from fastapi import HTTPException

from partyline import reports
from partyline.accept_sha import register_accept_route
from partyline.orchestrator_contracts import ReviewRequestIn, VerdictIn
from partyline.orchestrator_service import request_review, review_verdict
from partyline.orchestrator_sha_check import flag
from tests.orchestrator_fixture import TaskFixture, git


class RepinTest(TaskFixture):
    async def request(self, sha):
        return await request_review(self.runtime, self.worker, self.conv_id,
                                    ReviewRequestIn(sha=sha, what='fix', where='code'))

    async def test_repin_verdict_and_accept(self):
        await self.create()
        old = self.commit()
        first = await self.request(old)
        new = self.commit('fix')
        updated = await self.request(new)
        self.assertEqual(updated['sha'], new)
        self.assertEqual(updated['repositories'][0]['sha'], new)
        self.assertEqual(git(updated['review_worktree'], 'rev-parse', 'HEAD'), new)
        messages = self.db.list_messages(self.conv_id)
        self.assertTrue(any(old in m['body'] and new in m['body'] and
                            m['audience_attachment_id'] == first['reviewer_id'] for m in messages))
        reviewer = self.principal(first['reviewer_id'])
        for sha in (None, old):
            with self.assertRaises(HTTPException) as stale:
                await review_verdict(self.runtime, reviewer, self.conv_id,
                                     VerdictIn(verdict='approve', findings='ok', sha=sha))
            self.assertEqual(stale.exception.status_code, 409)
        approved = await review_verdict(self.runtime, reviewer, self.conv_id,
                                        VerdictIn(verdict='approve', findings='ok', sha=new))
        report = reports.get(self.db, approved['report_id'])['body']
        self.assertIn(new, report)
        self.assertIn('re-pinned', report)
        register_accept_route(self.app, self.runtime)
        self.actor = self.captain
        result = self.client.post(f'/api/conversations/{self.conv_id}/accept', json={'sha': new})
        self.assertEqual(result.status_code, 200, result.text)

    async def test_invalid_and_duplicate(self):
        await self.create()
        old = self.commit()
        first = await self.request(old)
        with self.assertRaises(HTTPException):
            await self.request('f' * 40)
        self.assertEqual(self.row()['sha'], old)
        self.assertEqual(git(first['review_worktree'], 'rev-parse', 'HEAD'), old)
        ident = first['reviewer_id']
        self.db.set_attachment_status(ident, 'exited', 'owner')
        await self.request(old)
        self.assertEqual(self.db.get_attachment(ident)['status'], 'running')

    async def test_sha_less_repin_and_live_duplicate(self):
        await self.create()
        old = self.commit()
        first = await self.request(old)
        before = len(self.db.list_messages(self.conv_id))
        duplicate = await self.request(None)
        self.assertEqual(duplicate['sha'], old)
        self.assertEqual(len(self.db.list_messages(self.conv_id)), before)
        new = self.commit('second')
        with patch('partyline.orchestrator_repin.flag', wraps=flag) as check:
            result = await request_review(self.runtime, self.worker, self.conv_id,
                                          ReviewRequestIn(what='missing abcdef123456', where='code'))
        self.assertEqual(result['sha'], new)
        self.assertEqual(git(first['review_worktree'], 'rev-parse', 'HEAD'), new)
        check.assert_awaited_once()
        self.assertEqual(check.call_args.args[2], 'missing abcdef123456 code')

    async def test_sha_less_repin_without_workspace_records(self):
        await self.create()
        old = self.commit()
        first = await self.request(old)
        self.db._exec('DELETE FROM task_workspaces WHERE conv_id=?', (self.conv_id,))
        new = self.commit('second')
        updated = await self.request(None)
        self.assertEqual(updated['sha'], new)
        self.assertEqual(git(first['review_worktree'], 'rev-parse', 'HEAD'), new)

    async def test_captain_gets_new_report(self):
        await self.create('captain')
        first = await self.request(self.commit())
        new = self.commit('fix')
        second = await self.request(new)
        self.assertIsNotNone(first['report_id'])
        self.assertIn(new, reports.get(self.db, second['report_id'])['body'])
        approved = await review_verdict(self.runtime, self.captain, self.conv_id,
                                        VerdictIn(verdict='approve', findings='ok', sha=new))
        self.assertEqual(approved['sha'], new)
