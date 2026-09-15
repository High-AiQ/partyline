"""On a line with one live process, a person's plain message is for that process.

The @mention is how a room with several processes says who acts next; on a
line with exactly one, there is nobody else it could be for, and typing the
handle in front of every message was the tax the person paid for a rule that
protected nothing. So a human message with no mention and no colon-address
on a line whose only live process is X reaches X as if it said @X. Only
humans get this shortcut: an agent's plain speech is a reply for the room,
and turning it into a wake would let two processes ring each other forever.
"""

from __future__ import annotations

from .mentions import addresses, line_addressed, mentioned_names

_LIVE = ("starting", "running")


def solo_process(db, conv_id: str) -> dict | None:
    """The line's one live process, or None when there are none or several."""
    live = [att for att in db.list_attachments(conv_id) if att["status"] in _LIVE]
    return live[0] if len(live) == 1 else None


def implied_addressee(db, message: dict) -> str | None:
    """The lower-cased handle a plain human message reaches on a solo line."""
    if message.get("sender_type") != "human" or message.get("audience_attachment_id"):
        return None
    body = str(message.get("body") or "")
    if mentioned_names(body) or line_addressed(body):
        return None
    alone = solo_process(db, message["conv_id"])
    return alone["name"].lower() if alone else None


def addressed(db, att: dict, messages: list[dict]) -> bool:
    """An @mention, a colon-address, or a person's plain word on a solo line."""
    name = str(att.get("name") or "")
    if addresses(name, messages):
        return True
    return db is not None and any(
        implied_addressee(db, message) == name.lower() for message in messages)
