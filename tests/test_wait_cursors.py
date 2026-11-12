"""A consumer that waits in a fresh task each time blocks until the next change."""

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from partyline import docker_events, memory_events
from partyline.db_events import DatabaseEvents
from partyline.file_events import FileEvents


async def settle(turns=200):
    loop = asyncio.get_running_loop()
    for _ in range(turns):
        tick = loop.create_future()
        loop.call_soon(tick.set_result, None)
        await tick


async def completed_waits(wait, turns=200):
    """Wait in a new task per round, as the event loops of the server do."""
    task, count = asyncio.create_task(wait()), 0
    loop = asyncio.get_running_loop()
    try:
        for _ in range(turns):
            tick = loop.create_future()
            loop.call_soon(tick.set_result, None)
            await tick
            if task.done():
                task.result()
                count += 1
                task = asyncio.create_task(wait())
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return count


class Watcher:
    def add(self, path):
        pass

    def retain(self, paths):
        pass

    async def close(self):
        pass


def backend(loop, changed, failed):
    return Watcher()


async def inline(function, *args):
    return function(*args)


class WaitCursorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:', check_same_thread=False)
        self.addCleanup(self.connection.close)
        for table in ('attachments', 'conversations'):
            self.connection.execute(f'CREATE TABLE {table} (id TEXT)')
        self.events = DatabaseEvents(self.connection)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.socket = Path(self.temporary.name) / 'docker.sock'

    def write(self, table):
        self.connection.execute(f'INSERT INTO {table} VALUES (?)', ('row',))

    async def test_one_database_change_completes_one_wait_however_the_waits_are_tasked(self):
        with self.events.subscribe('attachments') as subscription:
            self.write('attachments')
            self.assertEqual(await completed_waits(subscription.wait), 1)
            self.write('conversations')  # not subscribed
            self.assertEqual(await completed_waits(subscription.wait), 0)
            self.write('attachments')
            self.assertEqual(await completed_waits(lambda: subscription.wait(60)), 1)

    async def test_one_file_change_completes_one_wait_however_the_waits_are_tasked(self):
        async with FileEvents(self.socket, backend=backend) as files:
            files.changed({self.socket})
            self.assertEqual(await completed_waits(files.wait), 1)
            files.changed({self.socket})
            files.changed({self.socket})  # a burst is still one pulse for a waiter that was away
            self.assertEqual(await completed_waits(files.wait), 1)

    async def test_an_explicit_owner_keeps_its_own_cursor(self):
        async with FileEvents(self.socket, backend=backend) as files:
            files.changed({self.socket})
            owner = asyncio.current_task()
            self.assertEqual(await completed_waits(lambda: files.wait(owner)), 1)
            self.assertEqual(await completed_waits(files.wait), 1)  # the watch's own cursor

    async def test_the_memory_loop_reads_once_for_one_attachment_change(self):
        runtime = SimpleNamespace(db=SimpleNamespace(events=self.events), live={})
        scopes = Mock(return_value={})
        source = SimpleNamespace(sync=Mock(), close=Mock(return_value=None))
        with patch.object(memory_events, '_scope_map', scopes), \
                patch.object(memory_events.asyncio, 'to_thread', side_effect=inline):
            task = asyncio.create_task(memory_events.run(
                runtime, source_factory=lambda loop, notify: source, policy=SimpleNamespace()))
            await settle()
            self.assertEqual(scopes.call_count, 1)  # the initial sync
            self.write('attachments')
            await settle()
            self.assertEqual(scopes.call_count, 2)  # one change, one read, then silence
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_the_docker_loop_checks_grants_once_per_change(self):
        runtime = SimpleNamespace(db=SimpleNamespace(events=self.events))
        made = []

        def watch(*paths):
            made.append(FileEvents(*paths, backend=backend))
            return made[-1]

        grants = Mock(return_value=False)
        with patch.object(docker_events.docker_relay, 'host_socket', return_value=str(self.socket)), \
                patch.object(docker_events, 'FileEvents', watch), \
                patch.object(docker_events.docker_relay, 'any_grant', grants), \
                patch.object(docker_events.asyncio, 'to_thread', side_effect=inline):
            task = asyncio.create_task(docker_events.run(
                runtime, SimpleNamespace(watching=False)))
            await settle()
            self.assertEqual(grants.call_count, 1)
            self.write('conversations')
            await settle()
            self.assertEqual(grants.call_count, 2)
            made[0].changed({self.socket})
            await settle()
            self.assertEqual(grants.call_count, 3)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
