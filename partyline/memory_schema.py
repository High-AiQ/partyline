"""Append-only schema for memory-limit requests."""

MIGRATIONS = [
    # Requests survive restart and keep the original requester for the receipt.
    """CREATE TABLE IF NOT EXISTS memory_limit_requests(
        id TEXT PRIMARY KEY, attachment_id TEXT NOT NULL, conv_id TEXT NOT NULL,
        requester TEXT NOT NULL, requester_attachment_id TEXT, requested_limit TEXT NOT NULL,
        reason TEXT NOT NULL, created_at REAL NOT NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_limit_one_request_per_line "
    "ON memory_limit_requests(conv_id)",
    # Set when the worker is detached or its line retired: the row is kept so
    # Approve can say the worker is gone, but it no longer counts as pending.
    "ALTER TABLE memory_limit_requests ADD COLUMN expired_at REAL",
]
