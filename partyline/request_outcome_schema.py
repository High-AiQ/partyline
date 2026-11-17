"""How each filed approval request ended, so a late caller is told why it is gone."""

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS request_outcomes(
        kind TEXT NOT NULL, request_id TEXT NOT NULL, conv_id TEXT NOT NULL DEFAULT '',
        outcome TEXT NOT NULL, actor TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '',
        resolved_at REAL NOT NULL, PRIMARY KEY(kind, request_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_request_outcomes_age ON request_outcomes(resolved_at)",
]
