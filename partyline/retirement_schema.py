"""Retirement evidence survives conversation purge."""

MIGRATIONS = ["""CREATE TABLE IF NOT EXISTS retirement_audit(
    id TEXT PRIMARY KEY, principal TEXT NOT NULL, target TEXT NOT NULL,
    decision TEXT NOT NULL, evidence TEXT NOT NULL, recovery TEXT NOT NULL,
    error TEXT, created_at REAL NOT NULL
)""", """CREATE TABLE IF NOT EXISTS retirement_preserved_paths(
    path TEXT PRIMARY KEY, audit_id TEXT NOT NULL
)"""]
MIGRATIONS.extend([
    """CREATE TRIGGER IF NOT EXISTS retirement_review_removed AFTER DELETE ON review_worktrees
        BEGIN DELETE FROM retirement_preserved_paths WHERE path=OLD.path; END""",
    """CREATE TRIGGER IF NOT EXISTS retirement_scratch_removed AFTER DELETE ON scratch_worktrees
        BEGIN DELETE FROM retirement_preserved_paths WHERE path=OLD.path; END""",
])
