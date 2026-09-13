"""What changed under the root line since the last reminder, as data.

The first heartbeat repeated a goal the lead already knew and carried no
information, so the only possible reply was "no action taken" — sixty times in
one night. This module is the correction: every wake now answers *what changed*,
and a wake with nothing to say is not sent at all.

Message ids are the change detector, not hashes. They are monotonic, global,
and survive restarts, so a delta is exact and ordered; a hash could only say
*that* something differs. Hashing has exactly one job here — deciding whether
this snapshot is the same as the last one — and two things are deliberately
kept out of it:

* ``head_id``, because it moves for unrelated lines and for the monitor's own
  posted reminder. Hashing it would change the digest on every wake and
  suppression would never fire — the overnight failure, with extra JSON.
* ``quiet_wakes``, for the same reason one step removed: a counter that
  increments on every skip guarantees a different digest next time.

Nothing here reads a message body. The parent learns counts, senders, and
process state — the shape of activity, not its content.
"""

from __future__ import annotations

import hashlib
import json

from .db import Db
from .hierarchy import descendants

# Fan-out has to be bounded or the payload becomes the new noise. Both caps
# report what they dropped rather than truncating silently.
MAX_LINES = 20
MAX_AGENTS = 10
MAX_SENDERS = 8

# Consecutive quiet skips before a line holding open work is worth mentioning
# even though nothing happened. Silence with assigned work is the stall this
# monitor exists to catch; silence with an empty board is just a quiet room.


def _line_snapshot(
    db: Db, conv: dict, since_id: int, heartbeat_conv: str, owner_id: str
) -> dict:
    """One line's activity and process state since the reported boundary.

    The monitor's owner is excluded from the agent list. Its own unread count
    is circular — the wake it would earn is the wake that clears it — and a
    lead cannot be told anything useful about itself.
    """
    rows = db._exec(
        "SELECT id, sender, sender_type FROM messages"
        " WHERE conv_id=? AND id>? ORDER BY id",
        (conv["id"], since_id),
    ).fetchall()
    # The monitor's own reminders are not news. Counting them would make the
    # heartbeat permanently actionable because of itself.
    fresh = [
        row for row in rows
        if not (row["sender_type"] == "system" and conv["id"] == heartbeat_conv)
    ]
    senders = sorted({row["sender"] for row in fresh})
    agents = []
    for att in db.list_attachments(conv["id"]):
        if att["id"] == owner_id:
            continue
        # Exactly the exclusion `fresh` uses, and for the same reason. The
        # monitor's reminders are delivered to its owner alone, so on the
        # heartbeat's own line every peer is permanently "behind" by the count
        # of wakes posted so far. Counting them keeps `is_actionable` true
        # forever and quiet suppression dies after the very first wake.
        unread = db._exec(
            "SELECT COUNT(*) AS behind FROM messages"
            " WHERE conv_id=? AND id>? AND NOT (sender_type='system' AND ?)",
            (conv["id"], att["last_seen"], conv["id"] == heartbeat_conv),
        ).fetchone()["behind"]
        if unread or att["status"] not in ("running", "starting"):
            agents.append({
                # Keyed by attachment id, never handle: a replacement keeps the
                # handle and is a different process.
                "attachment_id": att["id"],
                "name": att["name"],
                "status": att["status"],
                "unread": unread,
            })
    return {
        "conv_id": conv["id"],
        "name": conv["name"],
        "new": len(fresh),
        "last_id": fresh[-1]["id"] if fresh else None,
        "senders": senders[:MAX_SENDERS],
        "senders_omitted": max(0, len(senders) - MAX_SENDERS),
        "agents": agents[:MAX_AGENTS],
        "agents_omitted": max(0, len(agents) - MAX_AGENTS),
    }


def build(db: Db, conv_id: str, since_id: int, owner_id: str = "") -> dict:
    """The delta for this root line and its descendants."""
    head = db._exec("SELECT MAX(id) AS head FROM messages").fetchone()["head"] or 0
    lines = []
    for ident in [conv_id, *descendants(db, conv_id)]:
        conv = db.get_conversation(ident)
        if conv is None or conv.get("archived_at"):
            continue
        line = _line_snapshot(db, conv, since_id, conv_id, owner_id)
        # Unchanged lines are omitted unless they are holding something: an
        # inbox of every quiet line is the noise this replaced.
        if line["new"] or line["agents"]:
            lines.append(line)
    reports = [
        {"id": row["id"], "revision": row["revision"], "child_conv_id": row["child_conv_id"]}
        for row in db._exec(
            "SELECT id, revision, child_conv_id FROM line_reports"
            " WHERE parent_conv_id=? AND acknowledged_at IS NULL ORDER BY id",
            (conv_id,),
        ).fetchall()
    ]
    return {
        "v": 1,
        "since_id": since_id,
        "head_id": head,
        "lines": lines[:MAX_LINES],
        "lines_omitted": max(0, len(lines) - MAX_LINES),
        "reports": reports,
    }


def canonical_hash(snapshot: dict) -> str:
    """A digest of what would make this wake worth sending.

    ``head_id`` is excluded deliberately — see the module docstring. Sorted
    keys and no whitespace so the same state always hashes the same way.
    """
    material = {key: value for key, value in snapshot.items() if key != "head_id"}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()[:16]


def is_actionable(snapshot: dict) -> bool:
    """Is there anything here a manager could act on?

    Mechanical on purpose: new speech, an unacknowledged report, or a process
    that is behind or not running. No judgement about importance — a rule the
    monitor applies is one an operator can predict.
    """
    if snapshot["reports"]:
        return True
    for line in snapshot["lines"]:
        if line["new"] or line["agents"]:
            return True
    return False



def render(snapshot: dict) -> str:
    """The payload as it rides the reminder: compact, sorted, readable."""
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
