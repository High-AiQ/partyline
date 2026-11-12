"""Durable cleanup failures and explicit automatic-retry suppression."""

MIGRATIONS = ["""CREATE TABLE IF NOT EXISTS storage_cleanup_kept(
    path TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    suppress_retry INTEGER NOT NULL DEFAULT 0
)"""]
