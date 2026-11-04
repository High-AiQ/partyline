"""Each review round can notify the captain after an earlier report was handled."""

from unittest.mock import patch

from partyline import reports
from partyline.orchestrator_contracts import ReviewRequestIn, VerdictIn
from partyline.orchestrator_notices import tell
from partyline.orchestrator_service import request_review, review_verdict
from tests.orchestrator_fixture import TaskFixture


class RereviewTest(TaskFixture):
    async def request(self, sha):
        return await request_review(self.runtime, self.worker, self.conv_id,
                                    ReviewRequestIn(sha=sha, what='fix', where='code and tests'))

    def acknowledge(self, row):
        record = reports.get(self.db, row['report_id'])
        self.assertIsNotNone(record['notified_at'])
        reports.acknowledge(self.db, record['id'], 'root', record['revision'])
        return record['id']

    async def test_captain_rereview_reports_and_wakes_once_after_acknowledged_round(self):
        await self.create('captain')
        first = await self.request(self.commit())
        first_id = self.acknowledge(first)
        changed = await review_verdict(self.runtime, self.captain, self.conv_id,
                                       VerdictIn(verdict='changes', findings='add regression'))
        self.assertEqual(changed['round'], 2)
        self.assertIsNone(changed['report_id'])
        sha = self.commit('fix regression')
        with patch('partyline.orchestrator_notices.tell', wraps=tell) as wake:
            second = await self.request(sha)
            self.assertNotEqual(second['report_id'], first_id)
            wake.assert_awaited_once_with(
                self.runtime, 'captain', f"needs attention: report {second['report_id']}")
            record = reports.get(self.db, second['report_id'])
            self.assertIsNotNone(record['notified_at'])
            self.assertIn('round 2', record['body'])
            self.assertIn(sha, record['body'])
            duplicate = await self.request(sha)
            self.assertEqual(duplicate['report_id'], second['report_id'])
            await review_verdict(self.runtime, self.captain, self.conv_id,
                                 VerdictIn(verdict='approve', findings='verified'))
            wake.assert_awaited_once()
        self.assertEqual(len(reports.list_for_parent(self.db, 'root')), 2)

    async def test_reviewer_approval_after_changes_replaces_acknowledged_report(self):
        await self.create('inspector')
        first = await self.request(self.commit())
        # Exercise a retained historical report pointer under a reviewer policy too.
        record, _ = reports.add(self.db, 'root', self.conv_id, 'task server',
                                'earlier escalation', notify=True)
        reports.mark_notified(self.db, record['id'], record['notifying_at'])
        self.db._exec('UPDATE task_reviews SET report_id=? WHERE conv_id=?',
                      (record['id'], self.conv_id))
        first_id = self.acknowledge(self.row())
        reviewer = self.principal(first['reviewer_id'])
        changed = await review_verdict(self.runtime, reviewer, self.conv_id,
                                       VerdictIn(verdict='changes', findings='add regression'))
        self.assertIsNone(changed['report_id'])
        second = await self.request(self.commit('fix regression'))
        self.assertEqual(second['round'], 2)
        self.assertEqual(len(reports.list_for_parent(self.db, 'root')), 1)
        with patch('partyline.orchestrator_notices.tell', wraps=tell) as wake:
            approved = await review_verdict(self.runtime, reviewer, self.conv_id,
                                            VerdictIn(verdict='approve', findings='verified'))
            self.assertNotEqual(approved['report_id'], first_id)
            wake.assert_awaited_once_with(
                self.runtime, 'captain', f"needs attention: report {approved['report_id']}")
            await self.request(second['sha'])
            wake.assert_awaited_once()
        self.assertIsNotNone(reports.get(self.db, approved['report_id'])['notified_at'])
        self.assertEqual(len(reports.list_for_parent(self.db, 'root')), 2)
