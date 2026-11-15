"""Idempotent helper update preferences, pauses and audit migrations."""
HELPER_UPDATES = [
    """CREATE TABLE IF NOT EXISTS screen_helper_preferences(
        device_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, pending INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS screen_helper_updates(
        device_id TEXT PRIMARY KEY, version TEXT NOT NULL, previous TEXT NOT NULL,
        deadline REAL NOT NULL, lines TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS screen_helper_update_audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL, actor TEXT NOT NULL,
        detail TEXT NOT NULL, created_at REAL NOT NULL
    )""",
]
