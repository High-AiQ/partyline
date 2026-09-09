"""A finished query, safe to read after its connection has moved on.

`Db._exec` used to return the live `sqlite3.Cursor` and release the lock, so
callers fetched their rows while another thread was already executing on the
same connection. SQLite tolerates that only until it does not: a reader could
come back with a row of all-``None`` columns, or with
``InterfaceError: bad parameter or other API misuse``.

Materializing inside the lock removes the window entirely — this object holds
values, not a position in a shared connection — while keeping the cursor
surface callers already use: ``fetchone``, ``fetchall``, ``rowcount``,
``lastrowid``, and iteration. ``fetchone`` still advances, because a cursor
does and quietly changing that would be a second, subtler bug.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any


class QueryResult:
    """The rows a statement produced, plus what it did."""

    __slots__ = ("_rows", "_position", "rowcount", "lastrowid")

    def __init__(
        self,
        rows: Sequence[Any] = (),
        rowcount: int = -1,
        lastrowid: int | None = None,
    ):
        self._rows: tuple[Any, ...] = tuple(rows)
        self._position = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self) -> Any | None:
        if self._position >= len(self._rows):
            return None
        row = self._rows[self._position]
        self._position += 1
        return row

    def fetchall(self) -> list[Any]:
        rows = list(self._rows[self._position :])
        self._position = len(self._rows)
        return rows

    def __iter__(self) -> Iterator[Any]:
        while (row := self.fetchone()) is not None:
            yield row

    def __len__(self) -> int:
        return len(self._rows)


def materialize(cursor) -> QueryResult:
    """Drain a live cursor while its lock is still held.

    A statement with no result set — DDL, a plain ``INSERT`` — is identified
    by ``description is None``, which is what sqlite3 documents, rather than
    by catching whatever a fetch happens to raise. Swallowing fetch errors
    here would hide precisely the corruption this module exists to prevent,
    so they propagate.

    ``rowcount`` and ``lastrowid`` are read *after* the drain: with
    ``RETURNING``, they are only final once the rows have been consumed.
    """
    rows = () if cursor.description is None else cursor.fetchall()
    return QueryResult(rows, cursor.rowcount, cursor.lastrowid)
