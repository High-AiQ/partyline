"""Each former database sweep waits for a mutation or a stored deadline."""

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from partyline import browser_snapshots, captain_handover, captain_handover_completion
from partyline import line_resource_routes, maintenance_events
from tests.adapter_event_clock import FixtureFiles


class Subscription:
    def __init__(self):
        self.entered = asyncio.Queue()
        self.changed = asyncio.Queue()
        self.changes = Mock()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def processing(self):
        return nullcontext()

    async def wait(self, delay=None):
        self.entered.put_nowait(delay)
        await self.changed.get()


class MaintenanceEventsTest(unittest.IsolatedAsyncioTestCase):
    async def assert_reacts(self, run, work, runtime, events):
        task = asyncio.create_task(run(runtime))
        try:
            self.assertIsNone(await events.entered.get())
            self.assertEqual(work.call_count, 1)
            await asyncio.sleep(0)
            self.assertEqual(work.call_count, 1)  # no timer drives another pass
            events.changed.put_nowait(None)
            self.assertIsNone(await events.entered.get())
            self.assertEqual(work.call_count, 2)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    def fixture(self):
        events = Subscription()
        db = SimpleNamespace(events=SimpleNamespace(subscribe=Mock(return_value=events)),
                             _exec=Mock(return_value=SimpleNamespace(fetchone=lambda: [None])))
        original = db._exec.return_value
        db._exec.side_effect = lambda sql, *a: (SimpleNamespace(fetchone=lambda: None)
            if sql.startswith('SELECT 1 FROM line_resource_claims') else original)
        return SimpleNamespace(db=db, live={}), events

    async def test_resource_grants_follow_mutations(self):
        runtime, events = self.fixture()
        with patch.object(line_resource_routes, 'maintain', new_callable=AsyncMock) as maintain:
            await self.assert_reacts(line_resource_routes.run, maintain, runtime, events)
        self.assertIn('line_resource_claims', runtime.db.events.subscribe.call_args.args)

    async def test_handover_completion_follows_mutations(self):
        runtime, events = self.fixture()
        with patch.object(captain_handover_completion, 'maintenance_once',
                          new_callable=AsyncMock) as maintain, \
                patch('partyline.retention_events.retention_notifications',
                      lambda *args: FixtureFiles()):
            await self.assert_reacts(captain_handover_completion.maintenance, maintain, runtime, events)

    async def test_failed_handover_work_arms_backoff_only_until_success(self):
        runtime, events = self.fixture()
        with patch.object(captain_handover_completion, 'maintenance_once',
                          new=AsyncMock(side_effect=[True, False])), \
                patch('partyline.retention_events.retention_notifications',
                      lambda *args: FixtureFiles()):
            task = asyncio.create_task(captain_handover_completion.maintenance(runtime))
            try:
                self.assertEqual(await events.entered.get(), 5)
                events.changed.put_nowait(None)
                self.assertIsNone(await events.entered.get())
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_offer_expiry_arms_the_persisted_deadline(self):
        runtime, events = self.fixture()
        runtime.db._exec.return_value.fetchone = lambda: [100]
        with patch.object(captain_handover.time, 'time', return_value=100):
            task = asyncio.create_task(captain_handover.expire_offers(runtime))
            try:
                self.assertEqual(await events.entered.get(), captain_handover.OFFER_TTL_SECONDS)
                self.assertEqual(runtime.db._exec.call_count, 2)
                events.changed.put_nowait(None)
                self.assertEqual(await events.entered.get(), captain_handover.OFFER_TTL_SECONDS)
                self.assertEqual(runtime.db._exec.call_count, 4)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

    async def test_task_cleanup_follows_database_or_git_ref_events(self):
        runtime, events = self.fixture()
        work = AsyncMock()
        with patch.object(maintenance_events, 'git_roots', return_value=[]), \
                patch.object(maintenance_events, 'FileEvents', FixtureFiles):
            async def run(runtime):
                await maintenance_events.tasks(runtime, work)
            await self.assert_reacts(run, work, runtime, events)

    async def test_hello_contains_instance_snapshots_for_account_and_line_modes(self):
        runtime = SimpleNamespace(db=Mock())
        speech = SimpleNamespace(settings=SimpleNamespace(
            model_dump=lambda: {'default': 'local', 'presets': []}))
        with patch.object(browser_snapshots, 'speech_snapshot', return_value=speech), \
                patch.object(browser_snapshots, '_view', return_value={'live_processes': 3}):
            for line in ('~account', 'line'):
                hello = await browser_snapshots.hello_payload(runtime, line, 'greg', 'build', '2.112.3', None)
                self.assertEqual(hello['type'], 'hello')
                self.assertEqual(hello['speech_settings']['default'], 'local')
                self.assertEqual(hello['resource_snapshot']['live_processes'], 3)
