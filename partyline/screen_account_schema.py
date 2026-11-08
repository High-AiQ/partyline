"""Account-scoped screen devices, preserving old line IDs as metadata."""


# Every boot copies and swaps the table, even after migration; this is data-safe:
# no foreign keys reference screen_devices, and the old and new column orders match.
MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS screen_devices_account(
        id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        conv_id TEXT, name TEXT NOT NULL, os TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
        created_at REAL NOT NULL, revoked_at REAL)""",
    "INSERT OR IGNORE INTO screen_devices_account SELECT * FROM screen_devices",
    "DROP TABLE IF EXISTS screen_devices",
    "ALTER TABLE screen_devices_account RENAME TO screen_devices",
    "CREATE INDEX IF NOT EXISTS idx_screen_devices_owner ON screen_devices(owner_id, revoked_at)",
]
