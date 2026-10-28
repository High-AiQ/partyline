"""Shipping detaches task processes; retention is opt-in and merged-only."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline.orchestrator_cleanup import shipped, tick, run
from partyline.orchestrator_contracts import ReviewRequestIn
from partyline.orchestrator_service import request_review
from tests.orchestrator_fixture import TaskFixture, git


class CleanupTest(TaskFixture):
    async def done(self):
        await self.create('none')
        sha = self.commit()
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=sha, what='done', where='code'))
        return self.row()

    async def test_shipping_detaches_but_default_retains_task_and_history(self):
        row = await self.done()
        self.assertFalse(shipped(self.db, row))
        await tick(self.runtime)
        self.assertEqual(self.db.get_attachment(row['implementer_id'])['status'], 'running')
        git(self.repo, 'merge', '--ff-only', row['sha'])
        await tick(self.runtime)
        self.assertEqual(self.db.get_attachment(row['implementer_id'])['status'], 'detached')
        self.assertEqual(self.row()['merged'], 1)
        self.assertIsNone(self.db.get_conversation(self.conv_id)['archived_at'])
        self.assertTrue(os.path.isdir(row['review_worktree']))

    async def test_auto_clean_requires_merged_clean_inactive_then_prunes_worktrees(self):
        self.db.set_setting('auto_clean_task_history', 'true')
        row = await self.done()
        await tick(self.runtime)
        self.assertIsNone(self.db.get_conversation(self.conv_id)['archived_at'])
        git(self.repo, 'merge', '--ff-only', row['sha'])
        cwd = self.db.get_conversation(self.conv_id)['cwd']
        with open(os.path.join(cwd, 'unfinished'), 'w') as fh:
            fh.write('not shipped')
        await tick(self.runtime)
        self.assertIsNone(self.db.get_conversation(self.conv_id)['archived_at'])
        os.unlink(os.path.join(cwd, 'unfinished'))
        self.runtime.presence = SimpleNamespace(is_working=lambda _: True)
        await tick(self.runtime)
        self.assertIsNone(self.db.get_conversation(self.conv_id)['archived_at'])
        self.runtime.presence = SimpleNamespace(is_working=lambda _: False)
        await tick(self.runtime)
        self.assertIsNotNone(self.db.get_conversation(self.conv_id)['archived_at'])
        self.assertFalse(os.path.exists(cwd))
        self.assertFalse(os.path.exists(row['review_worktree']))
        self.assertEqual(self.db.list_attachments(self.conv_id)[0]['status'], 'detached')
        self.assertEqual(self.row()['status'], 'done')

    async def test_maintenance_ignores_open_tasks_and_unverifiable_history(self):
        await self.create()
        await tick(self.runtime)
        row = self.row()
        self.assertFalse(shipped(self.db, row))
        self.db._exec("UPDATE conversations SET cwd='' WHERE id='root'")
        self.db._exec("DELETE FROM attachments WHERE id='captain'")
        row['sha'] = '0' * 40
        self.assertFalse(shipped(self.db, row))

    async def test_cleaner_continues_after_tick_error_and_cancels(self):
        import asyncio
        with patch('partyline.orchestrator_cleanup.tick', AsyncMock(side_effect=OSError('db'))), \
             patch('partyline.orchestrator_cleanup.asyncio.sleep',
                   AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertLogs('partyline.orchestrator_cleanup', level='ERROR'):
                with self.assertRaises(asyncio.CancelledError):
                    await run(self.runtime)

    async def test_newer_private_tip_prevents_cleanup_even_when_host_branch_is_merged(self):
        row = await self.done()
        git(self.repo, 'merge', '--ff-only', row['sha'])
        newer = self.commit('not merged')
        # Model the host's accepted ref lagging behind the fenced mirror.
        cwd = self.db.get_conversation(self.conv_id)['cwd']
        git(cwd, 'reset', '--hard', row['sha'])
        with patch('partyline.orchestrator_cleanup.mirror_branch_ref', return_value=newer):
            self.assertFalse(shipped(self.db, row))
            await tick(self.runtime)
        self.assertEqual(self.db.get_attachment(row['implementer_id'])['status'], 'running')
        self.assertIsNone(self.db.get_conversation(self.conv_id)['archived_at'])

    async def test_report_construction_runs_off_event_loop(self):
        import threading
        from partyline.orchestrator_notices import report

        await self.create('none')
        self.db._exec("UPDATE task_reviews SET status='done',report_id=NULL WHERE conv_id=?",
                      (self.conv_id,))
        main_thread = threading.get_ident()
        called = []

        def build(_db, _row):
            called.append(threading.get_ident())
            return 'done'

        with patch('partyline.orchestrator_notices.report_text', side_effect=build):
            await report(self.runtime, self.row())
        self.assertEqual(len(called), 1)
        self.assertNotEqual(called[0], main_thread)

    async def test_concurrent_report_creation_is_deduplicated(self):
        import asyncio
        import threading
        from partyline.orchestrator_notices import report

        await self.create('none')
        self.db._exec("UPDATE task_reviews SET status='done',report_id=NULL WHERE conv_id=?",
                      (self.conv_id,))
        both_started = threading.Barrier(2, timeout=5)

        def build(_db, _row):
            both_started.wait()
            return 'done'

        with patch('partyline.orchestrator_notices.report_text', side_effect=build):
            await asyncio.gather(report(self.runtime, self.row()), report(self.runtime, self.row()))
        reports = self.db._exec('SELECT COUNT(*) FROM line_reports').fetchone()[0]
        self.assertEqual(reports, 1)
