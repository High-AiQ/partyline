"""Persistent preset override fields."""

MIGRATIONS = [
    "ALTER TABLE task_reviews ADD COLUMN model TEXT",
    "ALTER TABLE task_reviews ADD COLUMN effort TEXT",
    "ALTER TABLE task_reviews ADD COLUMN review_model TEXT",
    "ALTER TABLE task_reviews ADD COLUMN review_effort TEXT",
    "ALTER TABLE attachments ADD COLUMN model_override TEXT",
    "ALTER TABLE attachments ADD COLUMN effort_override TEXT",
]
