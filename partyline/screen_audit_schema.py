"""Durable screen control audit migrations."""

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS screen_control_audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT, share_id TEXT NOT NULL, conv_id TEXT NOT NULL,
        agent TEXT NOT NULL, entry TEXT NOT NULL, previous_hash TEXT NOT NULL,
        entry_hash TEXT NOT NULL, message_id INTEGER
    )""",
    "CREATE INDEX IF NOT EXISTS idx_screen_audit_pending ON screen_control_audit(share_id, message_id, id)",
    "ALTER TABLE screen_control_audit ADD COLUMN created_at REAL NOT NULL DEFAULT 0",
    """CREATE TRIGGER IF NOT EXISTS delete_screen_audit AFTER DELETE ON conversations
        BEGIN DELETE FROM screen_control_audit WHERE conv_id=OLD.id; END""",
]

READ_LOG_MIGRATIONS = [
    "CREATE INDEX IF NOT EXISTS idx_screen_audit_line ON screen_control_audit(conv_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_screen_audit_message ON screen_control_audit(message_id) "
    "WHERE message_id IS NOT NULL",
]
