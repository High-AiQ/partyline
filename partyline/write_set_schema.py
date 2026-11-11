"""Add path lists and decision routing to pending write-set requests."""

MIGRATIONS = [
    "ALTER TABLE conversation_write_grant_requests ADD COLUMN paths TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE conversation_write_grant_requests ADD COLUMN human_only INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE conversation_write_grant_requests ADD COLUMN decider_name TEXT NOT NULL DEFAULT ''",
]
