"""What a resumed process is pasted of the messages addressed to it while it was away.

A process that kept its own session already holds most of them, and a long backlog pasted
whole costs its context a second time. So a resume pastes only what the session does not
already hold, newest first up to a bound, and says how to read the rest.
"""

from __future__ import annotations

import asyncio

from .message_queries import MESSAGE_SELECT, as_message
from .message_visibility import BRIDGE_DIGEST_CLAUSE
from .notice_policy import is_informational

REPLAY_CHARS = 8_000


def _size(message: dict) -> int:
    return len(str(message.get("body") or "")) + len(str(message.get("sender") or "")) + 5


def bound(att: dict, messages: list[dict], limit: int = REPLAY_CHARS) -> list[dict]:
    """The newest messages that fit ``limit``, led by one line saying what was left out."""
    kept, used = [], 0
    for message in reversed(messages):
        if kept and used + _size(message) > limit:
            break
        kept.append(message)
        used += _size(message)
    kept.reverse()
    left_out = messages[:len(messages) - len(kept)]
    if not left_out:
        return messages
    first, last = left_out[0]["id"], left_out[-1]["id"]
    note = {
        # The last omitted id: the cursor and the delivery receipt count it as part of this paste.
        "id": last, "conv_id": att["conv_id"], "sender": "system", "sender_type": "system",
        "audience_attachment_id": att["id"],
        "body": (f"({len(left_out)} earlier message(s) addressed to you are not repeated here: "
                 f"ids {first} to {last}. Read them only if you need them: "
                 f"read_messages(after_id={first - 1}, limit=50).)"),
    }
    return [note, *kept]


def _drop_seen(runtime, att: dict, messages: list[dict], seen: set[int]) -> list[dict]:
    """Credit the cursor over the unbroken run of seen messages; drop every seen one."""
    credited = 0
    for message in messages:
        if message["id"] not in seen:
            break
        credited = message["id"]
    if credited:
        runtime.db.set_last_seen(att["id"], credited, att.get("runtime_owner"))
    return [message for message in messages if message["id"] not in seen]


def credited_tail(runtime, att: dict, count: int = 5) -> list[dict]:
    """The newest messages the cursor already credits as pasted to this reader."""
    last = int(att.get("last_seen") or 0)
    if not last:
        return []
    rows = runtime.db._exec(
        MESSAGE_SELECT + " WHERE m.conv_id=? AND m.id<=? AND IFNULL(m.source_attachment_id,'') != ?"
        " AND IFNULL(m.audience_attachment_id,?) = ?"
        " AND NOT (m.source_attachment_id IS NULL AND m.sender = ?)" + BRIDGE_DIGEST_CLAUSE
        + " ORDER BY m.id DESC LIMIT ?",
        (att["conv_id"], last, att["id"], att["id"], att["id"], att["name"], count * 4)).fetchall()
    return [message for message in map(as_message, rows) if not is_informational(message)][:count]


async def for_resume(runtime, att: dict, pending: list[dict]) -> list[dict]:
    """``pending`` less what the kept session holds, bounded; the cursor follows what was dropped."""
    if att.get("adapter") == "opencode-v2" and att.get("cli_session") and pending:
        from partyline.adapters.bundled.opencode.seen import seen_ids

        credited = credited_tail(runtime, att)
        if int(att.get("last_seen") or 0) and not credited:
            seen = set()  # a cursor with no findable anchor vouches for nothing: replay it all
        else:
            seen = await asyncio.to_thread(seen_ids, att, pending, None, credited)
        pending = _drop_seen(runtime, att, pending, seen)
    return bound(att, pending)
