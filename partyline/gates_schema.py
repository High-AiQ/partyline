"""A line's declared gates: commands `accept` runs at the SHA when asked.

Split from `db_schema` the way `memory_schema` was, so this migration stays
append-only without growing the schema module past its line budget.
"""

MIGRATIONS = [
    # Finding 5.6: captains already reuse workers' gate evidence more than
    # they should; the declared commands let `accept` check at the SHA itself.
    """CREATE TABLE IF NOT EXISTS line_gates(
        conv_id TEXT PRIMARY KEY,
        commands TEXT NOT NULL,
        timeout_s INTEGER NOT NULL,
        updated_at REAL NOT NULL
    )""",
]
