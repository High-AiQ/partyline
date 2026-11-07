"""Durable local-tools audit migrations."""

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS local_tool_audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, conv_id TEXT NOT NULL,
        agent TEXT NOT NULL, kind TEXT NOT NULL, op TEXT NOT NULL, entry TEXT NOT NULL,
        code TEXT, code_sha TEXT, previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL,
        message_id INTEGER
    )""",
    "CREATE INDEX IF NOT EXISTS idx_local_tool_audit_pending ON local_tool_audit(session_id, message_id, id)",
    """CREATE TRIGGER IF NOT EXISTS delete_local_tool_audit AFTER DELETE ON conversations
        BEGIN DELETE FROM local_tool_audit WHERE conv_id=OLD.id; END""",
]
