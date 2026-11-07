"""Speech-recognizer presets edited in settings; append-only idempotent entries.

One row per database preset: its kind, the kind's fields as JSON (an API key is
only ever *named*, never stored), a default flag held by at most one row, and
an order. Config-file ``[[asr]]`` presets are not stored here.
"""

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS asr_presets(
        name TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        config TEXT NOT NULL DEFAULT '{}',
        is_default INTEGER NOT NULL DEFAULT 0,
        position INTEGER NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_asr_presets_default ON asr_presets(is_default) WHERE is_default=1",
]
