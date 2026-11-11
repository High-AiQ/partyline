"""A failed review install must reach the implementer, reviewer, and captain."""

from unittest.mock import patch

from fastapi import HTTPException

from partyline import reports
from partyline.orchestrator_contracts import ReviewRequestIn
from partyline.orchestrator_service import request_review
from partyline.review_install_sandbox import DependencyError
from tests.orchestrator_fixture import TaskFixture


class ReviewDependencyNoticeTest(TaskFixture):
    async def request(self, sha):
        return await request_review(self.runtime, self.worker, self.conv_id,
                                    ReviewRequestIn(sha=sha, what='fix', where='code'))

    async def test_repin_failure_notifies_reviewer_and_captain(self):
        await self.create()
        first = await self.request(self.commit())
        sha = self.commit('next')
        failure = DependencyError('offline failure')
        with patch('partyline.orchestrator_repin.move_task_review_worktrees', side_effect=failure):
            with self.assertRaises(HTTPException) as raised:
                await self.request(sha)
        self.assertIn('offline failure', raised.exception.detail)
        self.assertEqual(self.row()['status'], 'implementing')
        messages = self.db.list_messages(self.conv_id)
        self.assertTrue(any('offline failure' in message['body'] and
                            message['audience_attachment_id'] == first['reviewer_id']
                            for message in messages))
        self.assertTrue(any('offline failure' in report['body']
                            for report in reports.list_for_parent(self.db, 'root')))
