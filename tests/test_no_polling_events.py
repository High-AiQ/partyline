"""Event regressions use explicit notifications and fake OS waits, never real timers."""

import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from partyline.adapters.base import Adapter
from partyline.file_events import Changes, FileEvents
from partyline.db import Db
from partyline import process_events
from scripts.no_polling import violations


async def turn():
    await asyncio.sleep(0)


class EventTests(unittest.IsolatedAsyncioTestCase):
    async def test_notifications_before_wait_and_broadcast_to_every_waiter(self):
        changes = Changes()
        changes.notify()
        await changes.wait()
        first = asyncio.create_task(changes.wait())
        second = asyncio.create_task(changes.wait())
        # Each task consumes the already-published generation once.
        await asyncio.gather(first, second)

        async def waiting(ready):
            await changes.wait()
            ready.set()
            await changes.wait()

        ready = [asyncio.Event(), asyncio.Event()]
        tasks = [asyncio.create_task(waiting(event)) for event in ready]
        await asyncio.gather(*(event.wait() for event in ready))
        self.assertTrue(all(not task.done() for task in tasks))
        changes.notify()
        await asyncio.gather(*tasks)

    async def test_native_watch_registration_filters_events_and_closes(self):
        watcher = Mock(add=Mock(), retain=Mock(), close=AsyncMock(),
                       file_vnodes=False, directory_self_events=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'transcript.jsonl'
            async with FileEvents(path, backend=lambda *args: watcher) as events:
                events.changed({Path(directory) / 'unrelated'})
                self.assertEqual(events.changes.version, 0)
                events.changed({path})
                await events.wait()
            watcher.close.assert_awaited_once()

    async def test_native_watcher_failure_wakes_and_fails_the_consumer(self):
        watcher = Mock(add=Mock(), retain=Mock(), close=AsyncMock(),
                       file_vnodes=False, directory_self_events=True)
        with tempfile.TemporaryDirectory() as directory:
            async with FileEvents(directory, backend=lambda *args: watcher) as events:
                events.failed(OSError('notification source failed'))
                with self.assertRaisesRegex(OSError, 'notification source failed'):
                    await events.wait()

    async def test_sql_mutation_wakes_after_registration_and_self_work_does_not_recur(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Db(Path(directory) / 'test.db')
            try:
                with db.events.subscribe('conversations') as events:
                    waiter = asyncio.create_task(events.wait())
                    await turn()
                    self.assertFalse(waiter.done())
                    db.create_conversation('line', 'Line')
                    await waiter
                    # Consume on the task that will next wait.
                    await events.wait()
                    before = events.changes.version
                    with events.processing():
                        db._exec("UPDATE conversations SET name='Changed' WHERE id='line'")
                    waiter = asyncio.create_task(events.wait())
                    await waiter  # its own first generation, already delivered
                    await turn()
                    self.assertEqual(events.changes.version, before)
                self.assertEqual(db.events.listeners, set())
            finally:
                db.close()

    async def test_adapter_wait_ignores_clock_ticks_and_wakes_on_pty_or_exit(self):
        adapter = Adapter({'command': [], 'id': 'a'}, AsyncMock(), AsyncMock())
        wait = asyncio.create_task(adapter.wait_for_change())
        await turn()
        self.assertFalse(wait.done())
        adapter.changed()
        await wait
        # A new wait on this same task is suspended until a second event.
        ready = asyncio.Event()

        async def twice():
            await adapter.wait_for_change()
            ready.set()
            await adapter.wait_for_change()

        worker = asyncio.create_task(twice())
        await ready.wait()
        self.assertFalse(worker.done())
        adapter.abort_startup_prompt()  # process exit/stop event
        await worker

    async def test_deadline_wrappers_keep_the_consumers_cursor_between_waits(self):
        adapter = Adapter({'command': [], 'id': 'a'}, AsyncMock(), AsyncMock())
        ready = asyncio.Event()
        adapter.changed()

        async def twice():
            await adapter.wait_for_change(10)
            ready.set()
            await adapter.wait_for_change(10)

        task = asyncio.create_task(twice())
        await ready.wait()
        for _ in range(3):
            await turn()
        self.assertFalse(task.done(), 'wait_for must not invent a new event consumer')
        adapter.changed()
        await task

    async def test_shared_tail_reopens_unlinked_inode_and_keeps_partial_record(self):
        adapter = Adapter({'command': [], 'id': 'a', 'name': 'agent'}, AsyncMock(), AsyncMock())
        adapter.proc = SimpleNamespace(poll=lambda: None)
        observed = []
        waiting = asyncio.Event()
        original = adapter.wait_for_change

        async def wait(timeout=None):
            waiting.set()
            return await original(timeout)

        adapter.wait_for_change = wait
        # The notification source is explicitly controlled; no filesystem timing.
        class Source:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        adapter.file_events = Source
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'transcript.jsonl'
            path.write_text('{"id": 1}\n')

            async def record(value):
                observed.append(value['id'])
                if value['id'] == 2:
                    adapter.proc = None

            tail = asyncio.create_task(adapter._tail_jsonl(str(path), record))
            await waiting.wait()
            self.assertEqual(observed, [1])
            path.unlink()
            path.write_text('{"id":')
            waiting.clear()
            adapter.changed()
            await waiting.wait()
            self.assertEqual(observed, [1])
            with path.open('a') as stream:
                stream.write(' 2}\n')
            adapter.changed()
            await tail
            self.assertEqual(observed, [1, 2])

    async def test_nonchild_exit_wait_uses_os_notification(self):
        with patch.object(process_events, 'wait_pid') as native:
            await process_events.process_exited(123)
        native.assert_called_once_with(123)


class GuardTests(unittest.TestCase):
    def test_timer_fetches_and_indirect_retry_callbacks_are_rejected(self):
        for source in ('setInterval(() => fetch("/api/state"), 1000);',
                       'function reload() { api.load(); } setTimeout(reload, 1000);',
                       'setTimeout(() => this.load(), 1000);'):
            self.assertTrue(violations('frontend/src/example.ts', source))

    def test_sleep_loops_and_nested_loop_functions_are_rejected(self):
        self.assertTrue(violations('partyline/example.py',
            'async def run():\n while True:\n  await asyncio.sleep(1)\n'))
        self.assertFalse(violations('partyline/example.py',
            'while True:\n def deadline():\n  time.sleep(1)\n'))

    def test_each_documented_category_is_allowed_but_unexplained_or_a_is_not(self):
        for category in 'bcde':
            self.assertFalse(violations('frontend/src/example.ts',
                f'// no-poll ({category}): documented reason\nsetTimeout(finish, 100);'))
        for comment in ('// no-poll (a): check for changes', '// no-poll (b):'):
            self.assertTrue(violations('frontend/src/example.ts', comment + '\nsetTimeout(fetch, 100);'))

    def test_memory_sampler_poll_is_rejected(self):
        self.assertTrue(violations('partyline/memory_sampler.py',
            'while True:\n await asyncio.sleep(INTERVAL)\n'))
