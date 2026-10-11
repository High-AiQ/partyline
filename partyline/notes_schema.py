"""The line notebook: notes that survive compaction and restarts (finding 2.13).

Split from `db_schema` the way `memory_schema` and `idempotency_schema` were:
append-only idempotent entries without growing the schema module past its
line budget. Three scopes share one table — `tree` is stored on the tree's
root line, `line` on the line itself, and `attachment` is keyed by the
process's attachment id, so a process owns exactly one row.
"""

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS line_notes(
        conv_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        attachment_id TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL,
        updated_at REAL NOT NULL,
        PRIMARY KEY(conv_id, scope, attachment_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_line_notes_line ON line_notes(conv_id, scope)",
]
