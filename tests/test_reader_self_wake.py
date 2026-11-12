"""Real Linux watcher regression for SQLite readers of a live WAL."""
import asyncio
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.adapters.bundled.codex import thread_history
from partyline.adapters.bundled.opencode import adapter as opencode
from partyline.adapters.bundled.hermes.adapter import PartylineAdapter as Hermes
from partyline.file_events import Changes, FileEvents


@unittest.skipUnless(sys.platform == 'linux', 'Linux inotify regression')
class ReaderWakeTest(unittest.IsolatedAsyncioTestCase):
    async def test_codex_tail_does_not_wake_itself(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / thread_history.STORE_NAME
            writer = sqlite3.connect(path)
            self.addCleanup(writer.close)
            writer.executescript('PRAGMA journal_mode=WAL; CREATE TABLE thread_items '
                '(thread_id, item_id, item_type, created_at_ms, item_json); '
                'CREATE TABLE thread_turns (thread_id, turn_id, status, started_at);')
            changes = Changes()
            class Adapter:
                spawned_at = 0
                att = {'name': 'test'}
                count = 0
                _changes = changes
                def alive(self): return self.count < 20
                def event_time(self): return 0
                def mark_ready(self): pass
                async def wait_for_change(self, timeout=None):
                    self.count += 1
                    for _ in range(5):
                        await asyncio.sleep(0)
            async with FileEvents(path, changes=changes):
                await thread_history.tail_thread_history(Adapter(), home, 'thread')
                self.assertEqual(changes.version, 0)

    async def test_opencode_discovery_does_not_wake_itself(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / 'opencode.db'
            writer = sqlite3.connect(path)
            self.addCleanup(writer.close)
            writer.executescript('PRAGMA journal_mode=WAL; CREATE TABLE session '
                '(id, directory, time_created);')
            async def noop(*args): pass
            reader = opencode.PartylineAdapter({'cwd': home, 'command': [], 'name': 'test'}, noop, noop)
            changes = Changes()
            self.addCleanup(lambda: reader._reader and reader._reader.close())
            with patch.object(opencode, 'STORE', path):
                async with FileEvents(path, changes=changes):
                    for _ in range(20):
                        reader._find_session()
                        for _ in range(5):
                            await asyncio.sleep(0)
                    self.assertEqual(changes.version, 0)
                    writer.execute("INSERT INTO session VALUES ('new', ?, 0)", (home,))
                    writer.commit()
                    for _ in range(5):
                        await asyncio.sleep(0)
                    self.assertGreater(changes.version, 0)

    async def test_hermes_persistent_reader_does_not_wake_itself(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / 'state.db'
            writer = sqlite3.connect(path)
            self.addCleanup(writer.close)
            writer.executescript('PRAGMA journal_mode=WAL; CREATE TABLE messages '
                '(id INTEGER, session_id TEXT);')
            async def noop(*args): pass
            reader = Hermes({'cwd': home, 'command': [], 'name': 'test'}, noop, noop)
            with patch.dict('os.environ', {'HERMES_HOME': home}):
                reader._db = reader._open_db()
                self.addCleanup(reader._db.close)
                changes = Changes()
                async with FileEvents(path, changes=changes):
                    for _ in range(20):
                        reader._latest_message_id('session')
                        for _ in range(5):
                            await asyncio.sleep(0)
                    self.assertEqual(changes.version, 0)


class SettlementTest(unittest.TestCase):
    def test_one_later_read_per_notification_and_errors_drop_it(self):
        from partyline.adapters.store_wake import StoreWake

        class Clock:
            _changes = Changes()
            now = 0.0
            def event_time(self): return self.now

        clock = Clock()
        wake = StoreWake(clock)
        clock._changes.notify()
        wake.read(wake.observed(), False)
        self.assertEqual(wake.delay(), 0.05)
        clock.now = 0.05
        wake.read(wake.observed(), False)
        self.assertIsNone(wake.delay())
        clock._changes.notify()
        wake.read(wake.observed(), False)
        wake.read(wake.observed(), False, error=True)
        self.assertIsNone(wake.delay())

    def test_notification_queued_before_first_scan_gets_a_later_look(self):
        from partyline.adapters.store_wake import StoreWake

        class Clock:
            _changes = Changes()
            def event_time(self): return 0.0

        clock = Clock()
        clock._changes.notify()
        wake = StoreWake(clock)
        wake.read(wake.observed(), False)
        self.assertEqual(wake.delay(), 0.05)

    def test_codex_fetches_only_new_item_bodies(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript('CREATE TABLE thread_items '
            '(thread_id, item_id, item_type, created_at_ms, item_json); '
            "INSERT INTO thread_items VALUES ('t', 'a', 'agentMessage', 1, 'old'); "
            "INSERT INTO thread_items VALUES ('t', 'b', 'agentMessage', 1, 'new');")
        statements = []
        db.set_trace_callback(statements.append)
        rows = thread_history.fetch_items(db, 't', 0, {'a'})
        self.assertEqual(rows, [('b', 'agentMessage', 1, 'new')])
        self.assertNotIn("'a'", statements[-1])
