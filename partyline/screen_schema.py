"""Idempotent persistence for paired screen helper devices."""

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS screen_devices(
        id TEXT PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        conv_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        os TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        created_at REAL NOT NULL,
        revoked_at REAL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_screen_devices_owner_line "
    "ON screen_devices(owner_id, conv_id, revoked_at)",
]
