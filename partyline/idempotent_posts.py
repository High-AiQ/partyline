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
from dataclasses import dataclass
import threading
import time

from .message_queries import select_message_by_id

WINDOW_SECONDS = 600.0
DERIVED_PREFIX = "d:"
DERIVED_WINDOW_SECONDS = 120.0
PRUNE_AFTER_SECONDS = 3600.0


@dataclass
class _ClaimState:
    claimed: bool = False
    users: int = 0
    waiters: int = 0


_KEY_CLAIMS: dict[tuple[int, str, str, str], _ClaimState] = {}
_KEY_CLAIMS_GUARD = threading.Lock()


def principal_identity(principal) -> str | None:
    """Return the stable, namespaced identity proven by the credential."""
    if principal.kind == "user" and principal.user_id is not None:
        return f"user:{principal.user_id}"
    if principal.kind == "machine" and principal.attachment_id:
        return f"machine:{principal.attachment_id}"
    return None


@asynccontextmanager
async def claim_key(db, caller_id: str, conv_id: str, client_key: str):
    """Serialize one caller's retries for one destination and key.

    Authorization is deliberately performed by the route before entering this
    claim. The lock spans persistence and delivery, so a waiter either replays
    the completed message or can retry after a failed attempt releases it.
    """
    identity = (id(db), caller_id, conv_id, client_key)
    with _KEY_CLAIMS_GUARD:
        state = _KEY_CLAIMS.setdefault(identity, _ClaimState())
        state.users += 1
    acquired = False
    waiting = False
    try:
        while not acquired:
            with _KEY_CLAIMS_GUARD:
                if not state.claimed:
                    state.claimed = True
                    acquired = True
                    if waiting:
                        state.waiters -= 1
                        waiting = False
                elif not waiting:
                    state.waiters += 1
                    waiting = True
            if not acquired:
                await asyncio.sleep(0.01)
        yield
    finally:
        with _KEY_CLAIMS_GUARD:
            if waiting:
                state.waiters -= 1
            if acquired:
                state.claimed = False
            state.users -= 1
            if state.users == 0:
                del _KEY_CLAIMS[identity]


def _storage_key(conv_id: str, client_key: str) -> str:
    """Keep persisted client keys independent across destination conversations."""
    return f"{conv_id}\x1f{client_key}"


def window_for(client_key: str) -> float:
    """The replay window: caller-made keys state intent, derived keys only retry."""
    return DERIVED_WINDOW_SECONDS if client_key.startswith(DERIVED_PREFIX) else WINDOW_SECONDS


def original_for_key(db, caller_id: str, client_key: str, conv_id: str) -> dict | None:
    """The message this typed caller posted with this key, within its window."""
    storage_key = _storage_key(conv_id, client_key)
    row = db._exec(
        "SELECT message_id, created_at FROM idempotent_posts"
        " WHERE sender=? AND client_key=? AND conv_id=?",
        (caller_id, storage_key, conv_id),
    ).fetchone()
    if row is None or row["created_at"] < time.time() - window_for(client_key):
        return None
    return select_message_by_id(db._exec, conv_id, row["message_id"])


def remember_key(db, caller_id: str, client_key: str, conv_id: str, message_id: int) -> None:
    """Record a successful post under its key; expired rows cannot replay, so prune."""
    db._exec("DELETE FROM idempotent_posts WHERE created_at < ?",
             (time.time() - PRUNE_AFTER_SECONDS,))
    db._exec(
        "INSERT OR REPLACE INTO idempotent_posts"
        " (sender, client_key, conv_id, message_id, created_at) VALUES (?,?,?,?,?)",
        (caller_id, _storage_key(conv_id, client_key), conv_id, message_id, time.time()),
    )
