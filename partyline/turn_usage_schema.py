"""Append-only, idempotent schema for per-response model token usage."""

MIGRATIONS = [
    # One row per model response (Claude message id, Codex response id, OpenCode row id).
    # Token columns are normalised: input is uncached prompt, output includes reasoning,
    # reasoning is a breakdown that never adds to total_tokens. `calls` holds only tool
    # names and sub-op names, never arguments or content.
    """CREATE TABLE IF NOT EXISTS turn_usage(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conv_id TEXT NOT NULL, attachment_id TEXT NOT NULL, adapter TEXT NOT NULL,
        response_id TEXT NOT NULL, model TEXT,
        input_tokens INTEGER NOT NULL DEFAULT 0, cache_read_tokens INTEGER NOT NULL DEFAULT 0,
        cache_write_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
        reasoning_tokens INTEGER NOT NULL DEFAULT 0, total_tokens INTEGER NOT NULL DEFAULT 0,
        context_tokens INTEGER, context_window INTEGER,
        calls TEXT NOT NULL DEFAULT '[]', timestamp REAL NOT NULL,
        UNIQUE(attachment_id, response_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_turn_usage_line_time ON turn_usage(conv_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_turn_usage_attachment_time ON turn_usage(attachment_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_turn_usage_time ON turn_usage(timestamp)",
    # Milliseconds the model took: the gap from the previous tool result or user message to this
    # response's completion. NULL where the transcript cannot say (never guessed).
    "ALTER TABLE turn_usage ADD COLUMN model_ms INTEGER",
    """CREATE TRIGGER IF NOT EXISTS delete_turn_usage AFTER DELETE ON conversations
        BEGIN DELETE FROM turn_usage WHERE conv_id=OLD.id; END""",
]
