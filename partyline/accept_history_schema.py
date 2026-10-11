"""Accept history: one row per accepted hand-off, with what the review caught.

Split from `db_schema` the way `memory_schema` was, so this migration stays
append-only without growing the schema module past its line budget.
"""

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS accept_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conv_id TEXT NOT NULL,
        sha TEXT NOT NULL,
        reviewer TEXT NOT NULL,
        findings TEXT NOT NULL,
        created_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_accept_history_conv "
    "ON accept_history(conv_id, created_at)",
]
