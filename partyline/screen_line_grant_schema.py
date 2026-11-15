"""Window grants belong to a line, never to one process; they survive detach, exit and rotation."""

MIGRATIONS = [
    # The first design bound a grant to one attachment. Live grants never survive a restart, so its table
    # and attachment triggers (still created above, for history) are dropped rather than migrated.
    "DROP TRIGGER IF EXISTS screen_window_attachment_ended",
    "DROP TRIGGER IF EXISTS screen_window_attachment_deleted",
    "DROP TRIGGER IF EXISTS screen_window_device_revoked",
    "DROP TABLE IF EXISTS screen_window_grants",
    """CREATE TABLE IF NOT EXISTS screen_line_window_grants(
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL REFERENCES screen_devices(id) ON DELETE CASCADE,
        conv_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        process TEXT NOT NULL,
        hwnd INTEGER NOT NULL,
        standing_access INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS idx_screen_line_window_grants_line ON screen_line_window_grants(conv_id)",
    """CREATE TRIGGER IF NOT EXISTS screen_line_window_device_revoked
        AFTER UPDATE OF revoked_at ON screen_devices WHEN NEW.revoked_at IS NOT NULL
        BEGIN DELETE FROM screen_line_window_grants WHERE device_id=NEW.id; END""",
    """CREATE TRIGGER IF NOT EXISTS screen_line_window_line_archived
        AFTER UPDATE OF archived_at ON conversations WHEN NEW.archived_at IS NOT NULL
        BEGIN DELETE FROM screen_line_window_grants WHERE conv_id=NEW.id; END""",
]
