"""Database paths that must be present for a fenced read-only bind.

The database is write-ahead (``db_wal.py``): its ``-wal`` and ``-shm`` files
live as long as the server's connection and are bound read-only beside it. A
file left in rollback mode has a ``-journal`` instead, which is deliberately
absent here: SQLite deletes it after every transaction, so a bind on it races
the server and bubblewrap refuses to start with a missing source.
"""

from __future__ import annotations

import os


def ensure(db) -> list[str]:
    """Create absent SQLite sidecars and the runtime lock, then return all paths."""
    paths = [db.path, db.runtime_lock_path,
             f"{db.path}-wal", f"{db.path}-shm"]
    for path in paths[1:]:
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
    return paths
