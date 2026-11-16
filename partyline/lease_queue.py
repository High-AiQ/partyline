"""The queue rules for shared-resource leases, and the lock that serializes them.

Pure database logic with no routes: `resource_leases` takes and releases through
it, and `lease_lifecycle` wakes whoever it promotes.
"""

from __future__ import annotations

import functools
import threading
import time

MAX_TTL_S = 4 * 3600

# Every transition (take, release, expiry, promotion) reads a snapshot of one
# name's queue and then writes from it; two interleaved transitions would
# resurrect a cancelled waiter next to a new holder. One reentrant lock makes
# each transition atomic against the others in this server process.
_TRANSITION = threading.RLock()


def _serialized(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        with _TRANSITION:
            return function(*args, **kwargs)
    return wrapper


def _purge_expired(db) -> None:
    """Drop expired holders. A queued waiter never times out: the server promotes
    and wakes it, so its place lasts until it is granted, released or its process ends."""
    db._exec("DELETE FROM resource_leases WHERE expires_at<=? AND waiting=0", (time.time(),))


def _promote(db, row: dict, now: float) -> None:
    """Turn one waiter into the holder, granting exactly the TTL it asked for,
    capped at the module maximum — queue time must not inflate the lease. The
    row is flagged for a wake: its owner may not be polling."""
    ttl = min(row.get("ttl_s") or MAX_TTL_S, MAX_TTL_S)
    # An UPDATE, never an upsert: a waiter cancelled meanwhile must stay gone.
    db._exec("UPDATE resource_leases SET waiting=0, expires_at=?, wake_pending=1 "
             "WHERE name=? AND holder_attachment=? AND waiting=1",
             (now + ttl, row["name"], row["holder_attachment"]))


def _rows(db, name: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Every row for one lease name: all, holders, and waiters in queue order."""
    rows = [dict(row) for row in db._exec(
        "SELECT * FROM resource_leases WHERE name=?", (name,)).fetchall()]
    held = [row for row in rows if not row["waiting"]]
    waiters = sorted((row for row in rows if row["waiting"]),
                     key=lambda row: row["created_at"])
    return rows, held, waiters


def grantable(held: list[dict], waiters: list[dict]) -> list[dict]:
    """The waiters the queue rules grant now: nothing while an exclusive holds;
    an exclusive waiter only first in line with the slot empty; a shared waiter
    only with no exclusive waiter ahead of it."""
    if any(row["mode"] == "exclusive" for row in held):
        return []
    granted: list[dict] = []
    for row in waiters:
        if row["mode"] == "exclusive":
            if not held and not granted:
                granted.append(row)
            break
        granted.append(row)
    return granted


def promote_free(db, name: str, now: float | None = None) -> list[dict]:
    """Promote every waiter of one lease name the queue rules allow; the
    promoted rows are flagged so the server can wake their owners."""
    now = time.time() if now is None else now
    promoted = grantable(*_rows(db, name)[1:])
    for row in promoted:
        _promote(db, row, now)
    return promoted


@_serialized
def promote_all(db) -> list[dict]:
    """Drop expired rows, then promote on every name that has waiters. Run
    wherever leases are touched or read, so expiry needs no timer."""
    _purge_expired(db)
    names = [row[0] for row in db._exec(
        "SELECT DISTINCT name FROM resource_leases WHERE waiting=1").fetchall()]
    return [row for name in names for row in promote_free(db, name)]
