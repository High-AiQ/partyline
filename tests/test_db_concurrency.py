"""Concurrent readers and writers must not see each other's statements.

`Db._exec` released the lock and handed back the live cursor, so callers
fetched their rows while another thread was already executing on the same
connection. The symptoms were not exceptions in the offending code: a reader
came back with a row whose every column was `None`, and occasionally with
`InterfaceError: bad parameter or other API misuse` raised from an unrelated
`get_conversation` several call frames away.

These are timing tests, so they are written to fail loudly rather than
flakily: the load is heavy enough that the old code failed on essentially
every run, and the assertion is on *corrupted results*, not on timing.
"""

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from partyline.db import Db
from partyline.query_result import QueryResult, materialize


class QueryResultTest(unittest.TestCase):
    """The cursor surface callers already depend on, minus the live cursor."""

    def test_fetchone_advances_like_a_cursor(self):
        result = QueryResult([1, 2])

        self.assertEqual(result.fetchone(), 1)
        self.assertEqual(result.fetchone(), 2)
        self.assertIsNone(result.fetchone())

    def test_fetchall_returns_what_is_left(self):
        result = QueryResult([1, 2, 3])
        result.fetchone()

        self.assertEqual(result.fetchall(), [2, 3])
        self.assertEqual(result.fetchall(), [], "a drained result stays drained")

    def test_rowcount_and_lastrowid_survive_materialization(self):
        result = QueryResult([], rowcount=1, lastrowid=42)

        self.assertEqual((result.rowcount, result.lastrowid), (1, 42))

    def test_real_statements_with_no_result_set(self):
        # Not a stand-in: DDL and a plain INSERT as SQLite actually reports
        # them, identified by `description is None` rather than by catching
        # whatever a fetch might raise.
        connection = sqlite3.connect(":memory:")
        try:
            cursor = connection.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
            self.assertIsNone(cursor.description, "DDL is how SQLite says 'no result set'")
            self.assertEqual(materialize(cursor).fetchall(), [])

            insert = materialize(connection.execute("INSERT INTO t(v) VALUES('a')"))
            self.assertEqual(insert.fetchall(), [])
            self.assertEqual(insert.rowcount, 1)
            self.assertEqual(insert.lastrowid, 1)

            update = materialize(connection.execute("UPDATE t SET v='b' WHERE v='a'"))
            self.assertEqual(update.rowcount, 1)

            select = materialize(connection.execute("SELECT v FROM t"))
            self.assertEqual([row[0] for row in select.fetchall()], ["b"])
        finally:
            connection.close()

    def test_rowcount_is_read_after_a_returning_statement_is_drained(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
            connection.executemany("INSERT INTO t(v) VALUES(?)", [("a",), ("a",)])

            result = materialize(
                connection.execute("UPDATE t SET v='b' WHERE v='a' RETURNING id")
            )

            self.assertEqual(len(result.fetchall()), 2)
            self.assertEqual(result.rowcount, 2, "rowcount is only final after the drain")
        finally:
            connection.close()

    def test_a_failing_fetch_is_propagated_not_swallowed(self):
        # Swallowing this is how a corrupt read becomes an empty read, which
        # is the failure mode this whole module exists to remove.
        class Exploding:
            description = (("v", None, None, None, None, None, None),)
            rowcount = -1
            lastrowid = None

            def fetchall(self):
                raise sqlite3.InterfaceError("bad parameter or other API misuse")

        with self.assertRaises(sqlite3.InterfaceError):
            materialize(Exploding())


class ConcurrentAccessTest(unittest.TestCase):
    READERS = 6
    WRITERS = 4
    ROUNDS = 250

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(Path(self.directory.name) / "partyline.db")
        self.db.create_conversation("c1", "line")
        self.db._exec(
            "UPDATE conversations SET parent_id=? WHERE id=?", ("p1", "c1")
        )

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def test_reads_stay_intact_while_other_threads_write(self):
        corrupt: list[object] = []
        errors: list[str] = []

        def read():
            for _ in range(self.ROUNDS):
                try:
                    row = self.db.get_conversation("c1")
                except Exception as exc:  # noqa: BLE001 - the point is to catch any
                    errors.append(f"{type(exc).__name__}: {exc}")
                    continue
                # The old failure mode was not an exception: it was a row
                # whose every column had come back None.
                if row is None or row["id"] != "c1" or row["parent_id"] != "p1":
                    corrupt.append(row)

        def write(worker: int):
            for index in range(self.ROUNDS):
                try:
                    self.db.add_message("c1", f"w{worker}", "agent", f"m{index}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=read) for _ in range(self.READERS)]
        threads += [
            threading.Thread(target=write, args=(worker,))
            for worker in range(self.WRITERS)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)

        self.assertEqual(errors, [], "a concurrent read or write raised")
        self.assertEqual(corrupt, [], "a read came back with another statement's state")

    def test_every_concurrent_insert_is_counted_once(self):
        # `lastrowid` is read from the same cursor the rows came from, so it
        # has to be captured under the lock as well.
        ids: list[int] = []
        lock = threading.Lock()

        def write(worker: int):
            for index in range(self.ROUNDS):
                message = self.db.add_message("c1", f"w{worker}", "agent", f"m{index}")
                with lock:
                    ids.append(message["id"])

        threads = [
            threading.Thread(target=write, args=(worker,))
            for worker in range(self.WRITERS)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)

        expected = self.WRITERS * self.ROUNDS
        self.assertEqual(len(ids), expected)
        self.assertEqual(len(set(ids)), expected, "two writers were handed one row id")
        # `list_messages` pages at 500 by default, so ask the table directly
        # rather than asserting against a limit that has nothing to do with
        # concurrency.
        stored = self.db._exec(
            "SELECT COUNT(*) AS total FROM messages WHERE conv_id=?", ("c1",)
        ).fetchone()
        self.assertEqual(stored["total"], expected)


if __name__ == "__main__":
    unittest.main()
