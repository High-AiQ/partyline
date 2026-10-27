"""Attachment opt-in for counting raw processes."""

MIGRATIONS = ["ALTER TABLE attachments ADD COLUMN counts_toward_total INTEGER NOT NULL DEFAULT 0"]
