"""Window grants are bound to one attachment activation, never a reusable handle."""

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS screen_window_grants(
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL REFERENCES screen_devices(id) ON DELETE CASCADE,
        attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
        runtime_owner TEXT,
        title TEXT NOT NULL,
        process TEXT NOT NULL,
        hwnd INTEGER NOT NULL
    )""",
    """CREATE TRIGGER IF NOT EXISTS screen_window_attachment_ended
        AFTER UPDATE OF status,runtime_owner ON attachments
        WHEN NEW.status NOT IN ('starting','running') OR NEW.runtime_owner IS NOT OLD.runtime_owner
        BEGIN DELETE FROM screen_window_grants WHERE attachment_id=NEW.id; END""",
    """CREATE TRIGGER IF NOT EXISTS screen_window_attachment_deleted AFTER DELETE ON attachments
        BEGIN DELETE FROM screen_window_grants WHERE attachment_id=OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS screen_window_device_revoked AFTER UPDATE OF revoked_at ON screen_devices
        WHEN NEW.revoked_at IS NOT NULL
        BEGIN DELETE FROM screen_window_grants WHERE device_id=NEW.id; END""",
]
