"""Resource leases: who holds a host capability, who waits, until when.

Split from `db_schema` the way `memory_schema` was, so this migration stays
append-only without growing the schema module past its line budget.
"""

MIGRATIONS = [
    # Finding 2.10: three lines each kept "one Godot at a time" as prose in a
    # topic and had no way to know. A lease names the capability, the holder,
    # and its expiry; waiters are stored so the captain's line can say how
    # many are queued.
    """CREATE TABLE IF NOT EXISTS resource_leases(
        name TEXT NOT NULL,
        holder_attachment TEXT NOT NULL,
        holder_handle TEXT NOT NULL,
        holder_line TEXT NOT NULL DEFAULT '',
        mode TEXT NOT NULL,
        waiting INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        PRIMARY KEY(name, holder_attachment)
    )""",
]
