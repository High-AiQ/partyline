"""Server mirror of each paired helper's authoritative standing window permission."""

MIGRATIONS = [
    "CREATE TABLE IF NOT EXISTS screen_device_window_access(device_id TEXT PRIMARY KEY, "
    "enabled INTEGER NOT NULL DEFAULT 0, owner_conv_id TEXT REFERENCES conversations(id) ON DELETE SET NULL)",
    "ALTER TABLE screen_line_window_grants ADD COLUMN standing_access INTEGER NOT NULL DEFAULT 0",
]
