"""Write-ahead logging for the server's database, with checkpoints off the event loop.

A rollback journal syncs the journal, the database and their directory on every
commit, and every commit here runs on the event loop: one slow sync on a busy disk
held the whole server for seconds, long enough for turn receipts to time out. In
write-ahead mode a commit appends to the log without syncing; the syncs happen in
a checkpoint, which a worker thread runs on a connection of its own.

`synchronous=NORMAL` keeps the database consistent through a power loss and a
process crash loses nothing; only a power loss can drop the last few commits.
"""

from __future__ import annotations

import logging
import sqlite3
import threading

logger = logging.getLogger(__name__)

# Mutating statements between background checkpoints: a few megabytes of log.
CHECKPOINT_WRITES = 500
# SQLite's own checkpoint, on the committing thread, only if the worker falls far behind.
BACKSTOP_PAGES = 16384


class WalConnection(sqlite3.Connection):
    """The server's connection; it owns the worker that checkpoints its log."""

    checkpointer = None

    def wrote(self, _statement=None) -> None:
        if self.checkpointer is not None:
            self.checkpointer.wrote()

    def close(self) -> None:
        if self.checkpointer is not None:
            self.checkpointer.stop()
        super().close()


class Checkpointer:
    """Checkpoints when enough has been written; it never wakes on a clock."""

    def __init__(self, path: str):
        self.path = path
        self.writes = 0
        self.wake = threading.Event()
        self.stopped = False
        self.thread = None

    def wrote(self) -> None:
        self.writes += 1
        if self.writes < CHECKPOINT_WRITES or self.stopped:
            return
        self.writes = 0
        if self.thread is None:
            self.thread = threading.Thread(target=self.run, name="db-checkpoint", daemon=True)
            self.thread.start()
        self.wake.set()

    def checkpoint(self, connection) -> None:
        try:
            connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()
        except sqlite3.Error:
            logger.warning("database checkpoint failed; the next one retries", exc_info=True)

    def run(self) -> None:
        connection = sqlite3.connect(self.path)
        try:
            while True:
                self.wake.wait()
                self.wake.clear()
                if self.stopped:
                    return
                self.checkpoint(connection)
        finally:
            connection.close()

    def stop(self) -> None:
        self.stopped = True
        self.wake.set()
        if self.thread is not None:
            self.thread.join()


def connect(path) -> sqlite3.Connection:
    """Open the server's connection, in write-ahead mode wherever the file allows it."""
    connection = sqlite3.connect(path, check_same_thread=False, factory=WalConnection)
    try:
        mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    except sqlite3.OperationalError:
        mode = None  # another process holds the file in its old mode; the next start converts it
    if str(mode).lower() != "wal":
        if mode != "memory":
            logger.warning("database stays in %s journal mode; commits sync on the event loop",
                           mode or "its current")
        return connection
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(f"PRAGMA wal_autocheckpoint={BACKSTOP_PAGES}")
    connection.checkpointer = Checkpointer(str(path))
    return connection
