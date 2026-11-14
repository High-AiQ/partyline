"""Durable per-round reviewer progress and nudge bookkeeping."""

MIGRATIONS = [
    "ALTER TABLE task_reviews ADD COLUMN reviewer_stall_report_id INTEGER",
    "ALTER TABLE task_reviews ADD COLUMN reviewer_nudged INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE task_reviews ADD COLUMN reviewer_env_gap INTEGER NOT NULL DEFAULT 0",
]
