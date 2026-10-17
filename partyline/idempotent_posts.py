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

import asyncio
from contextlib import asynccontextmanager
import threading
import time

from .message_queries import select_message_by_id

WINDOW_SECONDS = 600.0
DERIVED_PREFIX = "d:"
DERIVED_WINDOW_SECONDS = 120.0
PRUNE_AFTER_SECONDS = 3600.0

_KEY_LOCKS: dict[tuple[int, str, str, str], tuple[threading.Lock, int]] = {}
_KEY_LOCKS_GUARD = threading.Lock()


@asynccontextmanager
async def claim_key(db, sender: str, conv_id: str, client_key: str):
    """Serialize one caller's retries for one destination and key.

    Authorization is deliberately performed by the route before entering this
    claim. The lock spans persistence and delivery, so a waiter either replays
    the completed message or can retry after a failed attempt releases it.
    """
    identity = (id(db), sender, conv_id, client_key)
    with _KEY_LOCKS_GUARD:
        lock, users = _KEY_LOCKS.get(identity, (threading.Lock(), 0))
        _KEY_LOCKS[identity] = (lock, users + 1)
    acquire = asyncio.create_task(asyncio.to_thread(lock.acquire))
    acquired = False
    try:
        try:
            await asyncio.shield(acquire)
            acquired = True
        except asyncio.CancelledError:
            # A worker thread cannot be cancelled while waiting on acquire.
            # Wait for its result and release so cancellation cannot leak a claim.
            await acquire
            lock.release()
            raise
        yield
    finally:
        if acquired:
            lock.release()
        with _KEY_LOCKS_GUARD:
            current_lock, users = _KEY_LOCKS[identity]
            if users == 1:
                del _KEY_LOCKS[identity]
            else:
                _KEY_LOCKS[identity] = (current_lock, users - 1)


def _storage_key(conv_id: str, client_key: str) -> str:
    """Keep keys independent across destination conversations in the legacy table."""
    return f"{conv_id}\x1f{client_key}"


def window_for(client_key: str) -> float:
    """The replay window: caller-made keys state intent, derived keys only retry."""
    return DERIVED_WINDOW_SECONDS if client_key.startswith(DERIVED_PREFIX) else WINDOW_SECONDS


def original_for_key(db, sender: str, client_key: str, conv_id: str) -> dict | None:
    """The message this sender already posted with this key, within its window."""
    storage_key = _storage_key(conv_id, client_key)
    row = db._exec(
        "SELECT message_id, created_at FROM idempotent_posts"
        " WHERE sender=? AND client_key=?",
        (sender, storage_key),
    ).fetchone()
    # Existing keys written before destination scoping remain replayable only
    # on the conversation recorded alongside them.
    if row is None:
        row = db._exec(
            "SELECT message_id, created_at FROM idempotent_posts"
            " WHERE sender=? AND client_key=? AND conv_id=?",
            (sender, client_key, conv_id),
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
        (sender, _storage_key(conv_id, client_key), conv_id, message_id, time.time()),
    )
