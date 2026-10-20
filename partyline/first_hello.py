"""A fresh worker's first hello, delivered to the captain who assigned it.

A hello without an @ is invisible to a process, and the worker pack tells
workers to wait for an @mention — so a replaced worker saying "waiting for
your @mention" used to leave both sides waiting (finding 5.7). A worker's
first message after attach or replace is therefore also delivered to the
line's live captain, once per activation: later messages route normally,
and a hello that already @mentions the captain needs no help. The captain is
woken on its own cursor — the hello is already on the line, so a private copy
would show the same words twice.
"""

from __future__ import annotations

from .mention_relay import live_manager


def mark_pending(runtime, att_id: str) -> None:
    """Arm the first-hello delivery for a starting activation."""
    runtime.first_hello_pending.add(att_id)


async def deliver_pending_first_hello(runtime, att_id: str, sender: str,
                                      body: str) -> bool:
    """Deliver a worker's first message to the line's live captain, once.

    Returns True when the captain was woken. The pending mark is spent
    on the first agent message whatever happens, so this can never become a
    chatter loop. A hello that already @mentions the captain routes
    normally and needs no wake; a line with no live captain has nobody to
    deliver to.
    """
    if att_id not in runtime.first_hello_pending:
        return False
    runtime.first_hello_pending.discard(att_id)
    att = runtime.db.get_attachment(att_id)
    if att is None:
        return False
    captain = live_manager(runtime, att["conv_id"])
    if captain is None or captain["id"] == att_id:
        return False
    if f"@{captain['name'].lower()}" in body.lower():
        return False  # the hello already rings the captain itself
    return await runtime.deliver_pending(att["conv_id"], captain, runtime.live[captain["id"]])
