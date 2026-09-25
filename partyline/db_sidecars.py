"""Database paths that must be present for a fenced read-only bind.

The rollback journal is deliberately absent: SQLite deletes ``-journal``
after every transaction, so a bind on it races the server and bubblewrap
refuses to start with a missing source. A reader without write access to
the main file cannot replay a hot journal anyway.
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
