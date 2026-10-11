"""Compaction visibility: per-attachment hook turns and compaction events.

Split from `db_schema` the way `memory_schema` and `idempotency_schema` were,
so this migration stays append-only without growing the schema module past
its line budget.
"""

MIGRATIONS = [
    # Finding 2.13: a worker's autocompact showed only on its own screen.
    # `trigger` is the harness's auto|manual; `turn` is the attachment's hook
    # turn counter at compaction time, which is what the thrash window counts.
    """CREATE TABLE IF NOT EXISTS compaction_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attachment_id TEXT NOT NULL,
        runtime_owner TEXT NOT NULL,
        trigger TEXT NOT NULL,
        turn INTEGER NOT NULL,
        created_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_compaction_events_att "
    "ON compaction_events(attachment_id, turn)",
    # The turn counter the thrash window counts, from the harness's own
    # UserPromptSubmit/Stop receipts. A fresh activation (new owner) starts
    # over, so a replaced process is judged on its own turns.
    """CREATE TABLE IF NOT EXISTS hook_turns(
        attachment_id TEXT PRIMARY KEY,
        runtime_owner TEXT NOT NULL,
        turns INTEGER NOT NULL
    )""",
]
