"""Server mirror of each paired helper's authoritative standing window permission."""

MIGRATIONS = [
    "CREATE TABLE IF NOT EXISTS screen_device_window_access(device_id TEXT PRIMARY KEY, "
    "enabled INTEGER NOT NULL DEFAULT 0, owner_conv_id TEXT REFERENCES conversations(id) ON DELETE SET NULL)",
    "ALTER TABLE screen_line_window_grants ADD COLUMN standing_access INTEGER NOT NULL DEFAULT 0",
]

# Retire the legacy source after copying, so removals survive another startup.
MIGRATIONS += [
    "CREATE TABLE IF NOT EXISTS screen_device_window_lines("
    "device_id TEXT NOT NULL REFERENCES screen_devices(id) ON DELETE CASCADE, "
    "conv_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, "
    "PRIMARY KEY(device_id,conv_id))",
    "INSERT OR IGNORE INTO screen_device_window_lines(device_id,conv_id) "
    "SELECT a.device_id,a.owner_conv_id FROM screen_device_window_access a "
    "JOIN screen_devices d ON d.id=a.device_id JOIN users u ON u.id=d.owner_id "
    "JOIN conversations c ON c.id=a.owner_conv_id WHERE d.revoked_at IS NULL",
    "UPDATE screen_device_window_access SET owner_conv_id=NULL WHERE owner_conv_id IS NOT NULL",
]
