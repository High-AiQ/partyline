"""Per-repository review environment overrides, kept in partyline settings, never in a repo."""

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS review_environments(
    repository TEXT NOT NULL,
    subpath TEXT NOT NULL DEFAULT '.',
    setup_command TEXT NOT NULL DEFAULT '',
    test_command TEXT NOT NULL DEFAULT '',
    set_by TEXT NOT NULL,
    set_at REAL NOT NULL,
    PRIMARY KEY(repository, subpath)
)""",
]
