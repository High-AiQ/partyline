"""Append-only restart recovery migrations."""

MIGRATIONS = [
    "ALTER TABLE restart_plan ADD COLUMN skipped TEXT NOT NULL DEFAULT '[]'",
]
