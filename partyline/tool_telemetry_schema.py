"""Append-only, idempotent tool telemetry schema."""

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS tool_calls(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conv_id TEXT NOT NULL, attachment_id TEXT NOT NULL, adapter TEXT NOT NULL,
        timestamp REAL NOT NULL, metrics TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_tool_calls_line_time ON tool_calls(conv_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_tool_calls_attachment_time ON tool_calls(attachment_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_tool_calls_time ON tool_calls(timestamp)",
    """CREATE TRIGGER IF NOT EXISTS delete_tool_calls AFTER DELETE ON conversations
        BEGIN DELETE FROM tool_calls WHERE conv_id=OLD.id; END""",
]
