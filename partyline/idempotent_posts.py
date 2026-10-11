"""Client-keyed idempotent POSTs: a retry returns the original message.

Finding 2.7 of the «3d game» report: the helper printed
`connection/request failed` for a POST that had actually succeeded, and a
retry posted the same words twice. The client makes the key, the server
remembers it: the same sender presenting the same key within the window
gets the original message back — 200 with the same id, not a second copy.

Two windows, told apart by the key's shape. A key the caller chose states an
intent ("this is my retry of that post") and replays for ten minutes. A key
*derived* from the request (the helper stamps ``d:``-prefixed ones) is just
what any identical command produces, so a captain re-sending the same words
on purpose must not be swallowed by it: derived keys replay for two minutes
only, and the response says ``replayed`` so the caller can tell.
"""

from __future__ import annotations

import time

from .message_queries import select_message_by_id

WINDOW_SECONDS = 600.0
DERIVED_PREFIX = "d:"
DERIVED_WINDOW_SECONDS = 120.0
PRUNE_AFTER_SECONDS = 3600.0


def window_for(client_key: str) -> float:
    """The replay window: caller-made keys state intent, derived keys only retry."""
    return DERIVED_WINDOW_SECONDS if client_key.startswith(DERIVED_PREFIX) else WINDOW_SECONDS


def original_for_key(db, sender: str, client_key: str, conv_id: str) -> dict | None:
    """The message this sender already posted with this key, within its window."""
    row = db._exec(
        "SELECT message_id, created_at FROM idempotent_posts"
        " WHERE sender=? AND client_key=?",
        (sender, client_key),
    ).fetchone()
    if row is None or row["created_at"] < time.time() - window_for(client_key):
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
