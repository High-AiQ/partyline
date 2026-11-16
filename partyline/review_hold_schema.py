"""Durable state for protecting a review SHA after an implementer message."""

MIGRATIONS = [
    "ALTER TABLE task_reviews ADD COLUMN review_hold_sha TEXT",
]
