"""Ack ping-pong between two processes: rate-limited, not eliminated (finding 2.4).

Two workers once exchanged "standing by" / "suite at 13 of 61" five times
while a suite ran: each @mention spent a turn and a wake to say nothing
that a reaction could not say. The detector is deliberately stateless — the
line's own history *is* the state. When a process mentions exactly one live
peer, that peer's last message mentioned it back, and nothing real happened
in between (no person spoke, no third process, no file, no reaction, no
accept), the streak counts up; the third consecutive such message is
refused. The API path answers 429; a terminal capture is still stored — the
transcript is the record — but its mention is not delivered and a notice
says why.

Exemptions are the design, not an omission: assignments and hand-offs must
always ring, so anything involving a captain is never limited, and people
never are. A streak breaks on any real message — one carrying a commit SHA,
or substantive past 280 characters, counts as work even when it mentions
the peer — and on a file, a reaction, or an accept since it began; a
silent commit with none of those does not break it.
"""

from __future__ import annotations

import re
import sqlite3

from .mentions import mentioned_names

SCAN = 12
SUBSTANTIVE_CHARS = 280
_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")


def _real_work(body: str) -> bool:
    """A SHA hand-off or a substantive reply is work, not an ack.

    Two workers genuinely collaborating — reviewing a slice, trading findings
    and SHAs — alternate mentions exactly like ack ping-pong, and a refused
    hand-off between peers is worse than an extra wake. Bare acks ("standing
    by", "suite at 13 of 61", "ok") stay short and carry no SHA, so the
    observed failure shape is still caught.
    """
    if len(" ".join(body.split())) > SUBSTANTIVE_CHARS:
        return True
    return any(
        any(char in "0123456789" for char in token)
        and any(char in "abcdef" for char in token)
        for token in _SHA_RE.findall(body)
    )


def _live(db, conv_id: str) -> dict:
    return {att["name"].lower(): att for att in db.list_attachments(conv_id)
            if att["status"] in ("starting", "running")}


def _has_files(db, message_id: int) -> bool:
    try:
        return db._exec(
            "SELECT 1 FROM images WHERE message_id=? LIMIT 1", (message_id,)
        ).fetchone() is not None
    except sqlite3.OperationalError:
        return False  # media schema not installed on this database


def pingpong_refusal(db, conv_id: str, sender: str, body: str,
                     exclude_id: int | None = None) -> str | None:
    """The live peer this message would be the third bare ack to, or None."""
    names = mentioned_names(body)
    if "all" in names:
        return None
    live = _live(db, conv_id)
    me = live.get(sender.lower())
    if me is None or me.get("is_lead"):
        return None  # a captain's mentions and a non-resident sender always ring
    targets = [live[name] for name in names
               if name in live and name != me["name"].lower()]
    if len(targets) != 1 or targets[0].get("is_lead"):
        return None  # several addressees is conversation, a captain is exempt
    if _real_work(body):
        return None  # this message itself carries work: a SHA, or real content
    target = targets[0]["name"].lower()
    sql = ("SELECT id, sender, sender_type, body, created_at, audience_attachment_id"
           " FROM messages WHERE conv_id=?")
    args: list = [conv_id]
    if exclude_id is not None:
        sql += " AND id != ?"
        args.append(exclude_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(SCAN)
    streak, expect_from, oldest = 0, target, None
    for row in db._exec(sql, args).fetchall():
        if row["sender_type"] == "system":
            continue  # partyline's own notices are not the pair talking
        if row["sender_type"] != "agent" or row["audience_attachment_id"]:
            break  # a person spoke, or a private copy landed: something happened
        who = row["sender"].lower()
        if who not in (me["name"].lower(), target) or who != expect_from:
            break  # a third process, or the pair out of order
        other = me["name"].lower() if who == target else target
        if other not in mentioned_names(row["body"]):
            break  # said something new rather than echoing back
        if _real_work(row["body"]):
            break  # a SHA hand-off or a substantive reply is collaboration, not an ack
        if _has_files(db, row["id"]):
            break  # a file upload is real activity
        streak += 1
        oldest = row["created_at"]
        expect_from = target if who == me["name"].lower() else me["name"].lower()
    if streak < 2 or oldest is None:
        return None  # fewer than two bare exchanges already: not yet the third
    since = db._exec(
        "SELECT 1 FROM reactions r JOIN messages m ON m.id=r.message_id"
        " WHERE m.conv_id=? AND r.created_at>=? LIMIT 1", (conv_id, oldest)).fetchone()
    accepted = db._exec(
        "SELECT 1 FROM accept_history WHERE conv_id=? AND created_at>=? LIMIT 1",
        (conv_id, oldest)).fetchone()
    return None if since or accepted else target


def refusal_message(target: str) -> str:
    return (f"ack ping-pong: nothing changed on the line since @{target}'s last "
            "message — react \U0001f440 instead of replying, or say something new")


def capture_notice(sender: str, target: str) -> str:
    return (f"⚠ ack ping-pong: @{sender}'s message was stored but its mention of "
            f"@{target} was not delivered — react \U0001f440 instead of replying, "
            "or say something new")
