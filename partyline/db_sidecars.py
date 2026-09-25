"""Database paths that must be present for a fenced read-only bind."""

from __future__ import annotations

import os


def ensure(db) -> list[str]:
    """Create absent SQLite sidecars and the runtime lock, then return all paths."""
    paths = [db.path, db.runtime_lock_path,
             f"{db.path}-wal", f"{db.path}-shm", f"{db.path}-journal"]
    for path in paths[1:]:
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
    return paths
