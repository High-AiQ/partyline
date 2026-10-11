"""Scratch worktrees: throwaway writable checkouts for integration builds.

Split from `db_schema` the way `memory_schema` was, so this migration stays
append-only without growing the schema module past its line budget.
"""

MIGRATIONS = [
    # Finding 2.15: a review checkout is for adversarial reads, but an
    # integration check needs to build and write. A scratch checkout is
    # recorded on the line and pruned when the line retires.
    """CREATE TABLE IF NOT EXISTS scratch_worktrees(
        conv_id TEXT NOT NULL,
        sha TEXT NOT NULL,
        path TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY(conv_id, sha)
    )""",
]
