"""Line bridges: a person-opened link between two lines in different trees.

Append-only idempotent entries, split from `db_schema` the way `notes_schema`
was. A bridge row names both lines and both ambassadors; it is never deleted,
only closed, so the audit log keeps its owner after the bridge ends.
`messages.bridge_id` stamps every bridge message — the sender's original and
the copy delivered to the counterpart — so the human-facing reads can hide
them and a person can read them back per bridge.
"""

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS line_bridges(
        id TEXT PRIMARY KEY,
        a_conv_id TEXT NOT NULL,
        a_attachment_id TEXT NOT NULL,
        b_conv_id TEXT NOT NULL,
        b_attachment_id TEXT NOT NULL,
        opened_at REAL NOT NULL,
        opened_by TEXT NOT NULL,
        closed_at REAL,
        closed_by TEXT,
        close_reason TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_line_bridges_a ON line_bridges(a_conv_id, closed_at)",
    "CREATE INDEX IF NOT EXISTS idx_line_bridges_b ON line_bridges(b_conv_id, closed_at)",
    "ALTER TABLE messages ADD COLUMN bridge_id TEXT",
]
