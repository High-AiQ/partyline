"""Append-only schema for captain-declared, exclusive line resources."""

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS line_resources(
        conv_id TEXT NOT NULL, name TEXT NOT NULL,
        PRIMARY KEY(conv_id,name))""",
    """CREATE TABLE IF NOT EXISTS line_resource_claims(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conv_id TEXT NOT NULL, name TEXT NOT NULL, attachment_id TEXT NOT NULL,
        note TEXT NOT NULL CHECK(length(note)<=500), created_at REAL NOT NULL,
        granted_at REAL, notice_id INTEGER, notified INTEGER NOT NULL DEFAULT 0,
        UNIQUE(conv_id,name,attachment_id))""",
    "CREATE UNIQUE INDEX IF NOT EXISTS line_resource_holder "
    "ON line_resource_claims(conv_id,name) WHERE granted_at IS NOT NULL",
    """CREATE TRIGGER IF NOT EXISTS line_resource_attachment_status
        AFTER UPDATE OF status,runtime_owner ON attachments
        WHEN NEW.status NOT IN ('starting','running') OR NEW.runtime_owner IS NOT OLD.runtime_owner
        BEGIN DELETE FROM line_resource_claims WHERE attachment_id=OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS line_resource_attachment_delete AFTER DELETE ON attachments
        BEGIN DELETE FROM line_resource_claims WHERE attachment_id=OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS line_resource_archive AFTER UPDATE OF archived_at ON conversations
        WHEN NEW.archived_at IS NOT NULL
        BEGIN DELETE FROM line_resource_claims WHERE attachment_id IN
            (SELECT id FROM attachments WHERE conv_id=OLD.id);
        DELETE FROM line_resource_claims WHERE conv_id=OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS line_resource_line_delete AFTER DELETE ON conversations
        BEGIN DELETE FROM line_resource_claims WHERE conv_id=OLD.id OR attachment_id IN
            (SELECT id FROM attachments WHERE conv_id=OLD.id);
        DELETE FROM line_resources WHERE conv_id=OLD.id; END""",
]
