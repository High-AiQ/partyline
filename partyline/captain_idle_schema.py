"""Remember idle verdicts until the captain detaches or work changes."""

MIGRATIONS = [
    "CREATE TABLE IF NOT EXISTS captain_idle_verdicts "
    "(attachment_id TEXT PRIMARY KEY, items TEXT NOT NULL)",
    "CREATE TRIGGER IF NOT EXISTS captain_idle_detach AFTER UPDATE OF status ON attachments "
    "WHEN NEW.status IN ('detached','exited') BEGIN "
    "DELETE FROM captain_idle_verdicts WHERE attachment_id=NEW.id; END",
    "CREATE TRIGGER IF NOT EXISTS captain_idle_delete AFTER DELETE ON attachments BEGIN "
    "DELETE FROM captain_idle_verdicts WHERE attachment_id=OLD.id; END",
]
