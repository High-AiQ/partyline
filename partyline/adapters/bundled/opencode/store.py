"""Reading one OpenCode v2 session out of its shared SQLite store."""

from __future__ import annotations

import contextlib
import json
import sqlite3


class SessionStore:
    """The store side of the v2 adapter: open it read-only and read only what is new."""

    _reader = None
    _store_version = None
    _store_open = True

    def _connect(self):
        """The one read-only connection this watcher keeps for its whole life.

        Opening and closing a write-ahead database closes its ``-wal`` and ``-shm`` files
        even for a reader, and that close is a notification on the very files being
        watched. With a connection per read, every read caused the next: the watcher
        never waited, and held a full core of the event loop whether or not the process
        was doing anything. Call it only inside ``_reading()``.
        """
        if not self._store_open:
            raise sqlite3.ProgrammingError("the OpenCode store watcher has stopped")
        if self._reader is None:
            assert self._store is not None
            self._reader = sqlite3.connect(f"{self._store.as_uri()}?mode=ro", uri=True,
                                           check_same_thread=False)
        return self._reader

    @contextlib.contextmanager
    def _reading(self):
        """The connection, held by one thread at a time.

        A read runs in a worker thread, and cancelling the watcher does not stop that
        thread. Closing the connection underneath it crashed the interpreter.
        """
        with self._store_lock:
            yield self._connect()

    def _close_store(self):
        """Close once no read is in flight; a read still queued finds the watcher stopped."""
        with self._store_lock:
            self._store_open = False
            reader, self._reader = self._reader, None
            if reader is not None:
                reader.close()

    @staticmethod
    def _decode(raw) -> dict:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def changed(self):
        """Terminal output and exit wake the watcher too, but put nothing new in the store."""
        self._other_wakes += 1
        super().changed()

    def _unsettled_rows(self):
        """This session's rows that are not settled yet, in order; None if nothing was committed.

        ``PRAGMA data_version`` moves only when another connection commits, so a
        notification that announces no commit (another reader closing its files) costs one
        pragma. The ids are listed without their bodies and only an unsettled row's body
        is read, so a long session's megabytes are not fetched again on every change.
        """
        with self._reading() as db:
            version = db.execute("PRAGMA data_version").fetchone()[0]
            if version == self._store_version:
                return None
            wanted = [ident for (ident,) in db.execute(
                "SELECT id FROM session_message WHERE session_id = ? AND seq >= ? ORDER BY seq",
                (self._session_id, self._claim_seq)) if ident not in self._seen]
            rows = []
            for start in range(0, len(wanted), 400):
                chunk = wanted[start:start + 400]
                rows += db.execute(
                    "SELECT id, type, data, seq FROM session_message WHERE session_id = ? "
                    f"AND id IN ({','.join('?' * len(chunk))})",
                    (self._session_id, *chunk)).fetchall()
            self._store_version = version
        return [row[:3] for row in sorted(rows, key=lambda row: row[3])]
