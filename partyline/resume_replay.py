"""What a resumed process is pasted of the messages addressed to it while it was away.

A process that kept its own session already holds some of them, and pasting those again costs
its context a second time. So a resume skips only what the session *provably* holds and says how
to reread it. Every other message is pasted in full, oldest first, on every adapter: a bound on
unseen messages would let the delivery receipt move the cursor past ones never delivered.
"""

from __future__ import annotations

import asyncio

from .message_queries import MESSAGE_SELECT, as_message
from .message_visibility import BRIDGE_DIGEST_CLAUSE
from .notice_policy import is_informational

READ_PAGE = 50


def _skipped_note(att: dict, skipped: list[dict]) -> dict:
    """One line naming the messages the kept session provably holds and so are not repeated."""
    first, last = skipped[0]["id"], skipped[-1]["id"]
    return {
        # The last skipped id: the delivery receipt counts it with this paste. Every message that
        # is not provably in the session is pasted after it, so the cursor never passes one.
        "id": last, "conv_id": att["conv_id"], "sender": "system", "sender_type": "system",
        "audience_attachment_id": att["id"],
        "body": (f"({len(skipped)} earlier message(s) addressed to you are already in your session and "
                 f"are not repeated here: ids {first} to {last}. To reread them: "
                 f"read_messages(after_id={first - 1}, limit={READ_PAGE}); more than {READ_PAGE}: repeat "
                 "with after_id set to the last id returned.)"),
    }


def _drop_seen(runtime, att: dict, messages: list[dict], seen: set[int]) -> tuple[list[dict], list[dict]]:
    """Credit the cursor over the unbroken run of seen messages; split seen from unseen."""
    credited = 0
    for message in messages:
        if message["id"] not in seen:
            break
        credited = message["id"]
    if credited:
        runtime.db.set_last_seen(att["id"], credited, att.get("runtime_owner"))
    return ([message for message in messages if message["id"] not in seen],
            [message for message in messages if message["id"] in seen])


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
    """``pending`` less what the kept session provably holds; the cursor follows only that run."""
    if att.get("adapter") == "opencode-v2" and att.get("cli_session") and pending:
        from partyline.adapters.bundled.opencode.seen import seen_ids

        credited = credited_tail(runtime, att)
        if int(att.get("last_seen") or 0) and not credited:
            seen = set()  # a cursor with no findable anchor vouches for nothing: replay it all
        else:
            seen = await asyncio.to_thread(seen_ids, att, pending, None, credited)
        pending, skipped = _drop_seen(runtime, att, pending, seen)
        if skipped:
            return [_skipped_note(att, skipped), *pending]
    return pending
