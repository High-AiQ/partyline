"""The server's database commits without syncing on the event loop."""

import os
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from partyline import db_wal
from partyline.db import Db


class WriteAheadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "partyline.db")

    def pragma(self, db, name):
        return db._exec(f"PRAGMA {name}").fetchone()[0]

    def test_a_new_database_is_write_ahead_with_normal_sync(self):
        db = Db(self.path)
        self.addCleanup(db.close)
        self.assertEqual(self.pragma(db, "journal_mode"), "wal")
        self.assertEqual(self.pragma(db, "synchronous"), 1)
        self.assertEqual(self.pragma(db, "wal_autocheckpoint"), db_wal.BACKSTOP_PAGES)

    def test_an_existing_rollback_database_with_empty_sidecars_is_converted_in_place(self):
        # The live shape before this change: delete mode, and the empty -wal and -shm
        # files the fence binds read-only.
        old = sqlite3.connect(self.path)
        old.execute("CREATE TABLE keepsake(value TEXT)")
        old.execute("INSERT INTO keepsake VALUES('kept')")
        old.commit()
        self.assertEqual(old.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        old.close()
        for suffix in ("-wal", "-shm"):
            open(self.path + suffix, "wb").close()
        db = Db(self.path)
        self.addCleanup(db.close)
        self.assertEqual(self.pragma(db, "journal_mode"), "wal")
        self.assertEqual(db._exec("SELECT value FROM keepsake").fetchone()[0], "kept")
        db.create_conversation("line", "Line")
        self.assertFalse(os.path.exists(self.path + "-journal"))

    def test_a_read_only_reader_sees_commits_while_the_server_holds_the_file(self):
        db = Db(self.path)
        self.addCleanup(db.close)
        db.create_conversation("line", "Line")
        reader = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self.addCleanup(reader.close)
        self.assertEqual(reader.execute("SELECT name FROM conversations").fetchone()[0], "Line")
        db.create_conversation("later", "Later")
        self.assertEqual(reader.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], 2)

    def test_a_file_another_process_holds_in_its_old_mode_still_opens(self):
        old = sqlite3.connect(self.path)
        self.addCleanup(old.close)
        old.execute("CREATE TABLE held(value TEXT)")
        old.execute("BEGIN EXCLUSIVE")
        impatient = lambda *args, connect=sqlite3.connect, **kwargs: connect(  # noqa: E731
            *args, timeout=0, **kwargs)
        with self.assertLogs("partyline.db_wal", "WARNING") as logs:
            with patch.object(db_wal.sqlite3, "connect", impatient):
                connection = db_wal.connect(self.path)
        self.addCleanup(connection.close)
        self.assertIsNone(connection.checkpointer)
        self.assertIn("journal mode", logs.output[0])

    def test_an_in_memory_database_needs_no_log_and_says_nothing(self):
        with self.assertNoLogs("partyline.db_wal", "WARNING"):
            connection = db_wal.connect(":memory:")
        self.assertIsNone(connection.checkpointer)
        connection.wrote()
        connection.close()


class CheckpointerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(os.path.join(self.directory.name, "partyline.db"))
        self.checkpointer = self.db.conn.checkpointer

    def test_writes_are_checkpointed_by_a_worker_and_never_by_the_committing_thread(self):
        ran = threading.Event()
        threads = []
        real = self.checkpointer.checkpoint

        def checkpoint(connection):
            threads.append(threading.current_thread())
            real(connection)
            ran.set()

        self.checkpointer.checkpoint = checkpoint
        self.db.create_conversation("line", "Line")
        self.assertIsNone(self.checkpointer.thread)  # a quiet database starts no thread
        with patch.object(db_wal, "CHECKPOINT_WRITES", 20):
            for index in range(25):
                self.db.add_message("line", "greg", "human", f"message {index}")
        self.assertTrue(ran.wait(5), "the worker never checkpointed")
        self.assertEqual([thread.name for thread in threads], ["db-checkpoint"])
        self.assertLess(self.checkpointer.writes, 20)
        # The checkpoint moved the log's pages into the database file itself.
        self.db.close()
        self.assertFalse(self.checkpointer.thread.is_alive())
        plain = sqlite3.connect(self.db.path)
        self.addCleanup(plain.close)
        self.assertEqual(plain.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 25)

    def test_a_failed_checkpoint_is_logged_and_the_next_one_still_runs(self):
        class Broken:
            def execute(self, _statement):
                raise sqlite3.OperationalError("disk I/O error")

        with self.assertLogs("partyline.db_wal", "WARNING"):
            self.checkpointer.checkpoint(Broken())
        self.db.close()

    def test_closing_stops_a_worker_that_is_waiting(self):
        with patch.object(db_wal, "CHECKPOINT_WRITES", 1):
            self.db.create_conversation("line", "Line")
        thread = self.checkpointer.thread
        self.assertIsNotNone(thread)
        self.db.close()
        self.assertFalse(thread.is_alive())
        self.checkpointer.wrote()  # a late trace after close starts nothing
        self.assertIs(self.checkpointer.thread, thread)


if __name__ == "__main__":
    unittest.main()
