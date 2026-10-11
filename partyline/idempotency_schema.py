"""Idempotent message posts: one (sender, client_key) pair names one message.

Split from `db_schema` the way `memory_schema` was, so this migration stays
append-only without growing the schema module past its line budget.
"""

MIGRATIONS = [
    # Finding 2.7: the client printed `connection/request failed` for a POST
    # that had succeeded, and the retry posted twice. The key is client-made;
    # the window here is enforced by the readers, not the table.
    """CREATE TABLE IF NOT EXISTS idempotent_posts(
        sender TEXT NOT NULL,
        client_key TEXT NOT NULL,
        conv_id TEXT NOT NULL,
        message_id INTEGER NOT NULL,
        created_at REAL NOT NULL,
        UNIQUE(sender, client_key)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_idempotent_posts_time ON idempotent_posts(created_at)",
    # A purged message's key row would replay nothing; drop it with the message.
    """CREATE TRIGGER IF NOT EXISTS delete_idempotent_posts AFTER DELETE ON messages
        BEGIN DELETE FROM idempotent_posts WHERE message_id=OLD.id; END""",
]
