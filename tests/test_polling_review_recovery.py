"""Failure recovery and persisted deadlines must not need unrelated mutations."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline import line_resource_routes, line_resources, maintenance_events, orchestrator_cleanup
from partyline import orchestrator_notices, reports
from partyline.orchestrator_store import task as task_row
from tests.adapter_event_clock import FixtureFiles
from tests.orchestrator_fixture import TaskFixture
from tests.test_polling_maintenance_events import Subscription


class RecoveryTests(TaskFixture):
    async def stop_worker(self, worker):
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    async def queued_grant(self):
        await self.create()
        line_resources.manage(self.db, 'root', 'declare', 'fixture')
        with patch('partyline.line_resources.probe'):
            line_resources.acquire(self.db, 'root', 'fixture', 'captain')
            line_resources.acquire(self.db, 'root', 'fixture', self.worker.attachment_id)
            line_resources.release(self.db, 'root', 'fixture', 'captain')

    async def test_grant_claim_is_recoverable_at_the_exact_expiry(self):
        await self.queued_grant()
        self.db._exec('UPDATE line_resource_claims SET notified=100')
        self.runtime.route_mentions.reset_mock()
        with patch('time.time', return_value=130):
            await line_resource_routes.maintain(self.runtime)
        self.assertEqual(self.db._exec('SELECT notified FROM line_resource_claims').fetchone()[0], 1)
        self.runtime.route_mentions.assert_awaited_once()

    async def test_failed_grant_notice_retries_on_backoff_then_stops(self):
        await self.queued_grant()
        events = Subscription()
        self.runtime.route_mentions = AsyncMock(side_effect=[OSError('delivery failed'), None])
        with patch.object(self.db.events, 'subscribe', return_value=events), \
                self.assertLogs('partyline.line_resource_routes', level='ERROR'):
            worker = asyncio.create_task(line_resource_routes.run(self.runtime))
            try:
                self.assertEqual(await events.entered.get(), 5)
                claim = self.db._exec('SELECT * FROM line_resource_claims').fetchone()
                self.assertEqual(claim['notified'], 0)
                # Advance the fake backoff deadline; no SQL mutation wakes it.
                events.changed.put_nowait(None)
                self.assertIsNone(await events.entered.get())
                delivered = self.db._exec('SELECT * FROM line_resource_claims').fetchone()
                self.assertEqual(delivered['notified'], 1)
                self.assertEqual(delivered['notice_id'], claim['notice_id'])
                self.assertEqual(self.runtime.route_mentions.await_count, 2)
            finally:
                await self.stop_worker(worker)

    async def persisted_report(self):
        await self.create('none')
        with patch('time.time', return_value=100):
            record, claimed = reports.add(self.db, 'root', self.conv_id, 'task server', 'done',
                                          notify=True)
        self.assertTrue(claimed)
        self.db._exec("UPDATE task_reviews SET status='done',report_id=? WHERE conv_id=?",
                      (record['id'], self.conv_id))
        self.runtime.route_mentions.reset_mock()
        return record

    async def test_restart_recovers_fresh_report_claim_at_its_deadline(self):
        record = await self.persisted_report()
        events = Subscription()
        now = 110

        async def notify(runtime):
            await orchestrator_notices.report(runtime, task_row(self.db, self.conv_id))

        with patch.object(self.db.events, 'subscribe', return_value=events) as subscribe, \
                patch.object(maintenance_events, 'FileEvents', FixtureFiles), \
                patch.object(maintenance_events, 'git_roots', return_value=[]), \
                patch('time.time', side_effect=lambda: now):
            worker = asyncio.create_task(maintenance_events.tasks(self.runtime, notify))
            try:
                self.assertEqual(await events.entered.get(), 20)
                self.runtime.route_mentions.assert_not_awaited()
                now = 130  # expire only the persisted claim, without changing database state
                events.changed.put_nowait(None)
                self.assertIsNone(await events.entered.get())
                self.assertIsNotNone(reports.get(self.db, record['id'])['notified_at'])
                self.runtime.route_mentions.assert_awaited_once()
                self.assertIn('line_reports', subscribe.call_args.args)
            finally:
                await self.stop_worker(worker)

    async def test_report_delivery_failure_retries_without_another_mutation(self):
        record = await self.persisted_report()
        self.db._exec('UPDATE line_reports SET notifying_at=NULL WHERE id=?', (record['id'],))
        events = Subscription()
        self.runtime.route_mentions = AsyncMock(side_effect=[OSError('offline'), None])
        # Use the real cleaner wrapper, report delivery and claim release paths.
        with patch.object(self.db.events, 'subscribe', return_value=events), \
                patch.object(maintenance_events, 'FileEvents', FixtureFiles), \
                patch.object(maintenance_events, 'git_roots', return_value=[]), \
                patch.object(orchestrator_cleanup, 'shipped', return_value=False), \
                self.assertLogs('partyline.orchestrator_cleanup', level='ERROR'):
            worker = asyncio.create_task(orchestrator_cleanup.run(self.runtime))
            try:
                self.assertEqual(await events.entered.get(), 5)
                self.assertIsNone(reports.get(self.db, record['id'])['notifying_at'])
                events.changed.put_nowait(None)  # fake retry deadline, no database event
                self.assertIsNone(await events.entered.get())
                self.assertIsNotNone(reports.get(self.db, record['id'])['notified_at'])
                self.assertEqual(self.runtime.route_mentions.await_count, 2)
            finally:
                await self.stop_worker(worker)

    async def test_secondary_repository_merge_is_the_only_cleanup_wakeup(self):
        await self.create('none')
        secondary = Path(self.directory.name) / 'secondary'
        metadata = secondary / '.git'
        metadata.mkdir(parents=True)
        (metadata / 'HEAD').write_text('before merge')
        self.db._exec('UPDATE task_reviews SET repositories=? WHERE conv_id=?',
                      (json.dumps([{'repository': str(secondary), 'sha': 'reviewed'}]), self.conv_id))
        events = Subscription()
        changes = events.changes = SimpleNamespace(notify=lambda: events.changed.put_nowait(None))
        watched = []
        passes = []

        class Files(FixtureFiles):
            def __init__(self, *roots, **kwargs):
                watched.append(roots)
                self.changes = kwargs['changes']

        async def cleanup(runtime):
            passes.append((metadata / 'HEAD').read_text())

        with patch.object(self.db.events, 'subscribe', return_value=events), \
                patch.object(maintenance_events, 'FileEvents', Files):
            worker = asyncio.create_task(maintenance_events.tasks(self.runtime, cleanup))
            try:
                self.assertIsNone(await events.entered.get())
                self.assertIn(metadata, watched[-1])
                self.assertEqual(passes, ['before merge'])
                (metadata / 'HEAD').write_text('merged')
                changes.notify()  # native directory event for this watched secondary repo
                self.assertIsNone(await events.entered.get())
                self.assertEqual(passes, ['before merge', 'merged'])
            finally:
                await self.stop_worker(worker)

    async def test_workspace_registration_wakes_and_adds_its_repository(self):
        await self.create('none')
        extra = Path(self.directory.name) / 'registered'
        metadata = extra / '.git'
        metadata.mkdir(parents=True)
        events = Subscription()
        watched = []

        class Files(FixtureFiles):
            def __init__(self, *roots, **kwargs):
                watched.append(roots)

        with patch.object(self.db.events, 'subscribe', return_value=events) as subscribe, \
                patch.object(maintenance_events, 'FileEvents', Files):
            worker = asyncio.create_task(maintenance_events.tasks(self.runtime, AsyncMock()))
            try:
                await events.entered.get()
                self.assertNotIn(metadata, watched[-1])
                self.db._exec('INSERT INTO task_workspaces VALUES(?,?,?,?,?)',
                              (self.conv_id, str(extra), str(extra), 'line/test', 'base'))
                events.changed.put_nowait(None)
                await events.entered.get()
                self.assertIn('task_workspaces', subscribe.call_args.args)
                self.assertIn(metadata, watched[-1])
            finally:
                await self.stop_worker(worker)
