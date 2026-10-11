"""Client-keyed idempotent POSTs: a retry returns the original message.

Finding 2.7 of the «3d game» report: the helper printed
`connection/request failed` for a POST that had actually succeeded, and a
retry posted the same words twice. The client makes the key, the server
remembers it: the same sender presenting the same key within the window
gets the original message back — 200 with the same id, not a second copy.
"""

from __future__ import annotations

import time

from .message_queries import select_message_by_id

WINDOW_SECONDS = 600.0
PRUNE_AFTER_SECONDS = 3600.0


def original_for_key(db, sender: str, client_key: str, conv_id: str) -> dict | None:
    """The message this sender already posted with this key, within the window."""
    row = db._exec(
        "SELECT message_id, created_at FROM idempotent_posts"
        " WHERE sender=? AND client_key=?",
        (sender, client_key),
    ).fetchone()
    if row is None or row["created_at"] < time.time() - WINDOW_SECONDS:
        return None
    return select_message_by_id(db._exec, conv_id, row["message_id"])


def remember_key(db, sender: str, client_key: str, conv_id: str, message_id: int) -> None:
    """Record a successful post under its key; expired rows cannot replay, so prune."""
    db._exec("DELETE FROM idempotent_posts WHERE created_at < ?",
             (time.time() - PRUNE_AFTER_SECONDS,))
    db._exec(
        "INSERT OR REPLACE INTO idempotent_posts"
        " (sender, client_key, conv_id, message_id, created_at) VALUES (?,?,?,?,?)",
        (sender, client_key, conv_id, message_id, time.time()),
    )
