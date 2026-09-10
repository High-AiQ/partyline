"""Posting a reminder, settling it, and deciding not to post at all.

Split from `heartbeat`, which holds configuration and ownership, when that
module reached its line cap. The division is real rather than clerical: this
file is the lifecycle of one wake — claim, post, deliver, settle — and the
quiet accounting that lets most wakes never happen.

The quiet path is the point of the redesign. A monitor that speaks every
interval regardless of state trains its reader to ignore it, which is exactly
what happened on the first night: sixty reminders, sixty "no action taken".
"""

from __future__ import annotations

import time

from .db import Db, MessageRow
from .message_queries import as_message
from . import heartbeat


def record_quiet_skip(db: Db, now: float, snapshot_hash: str) -> int:
    """Nothing worth saying: bank the interval, keep the delta owed.

    `since_id` deliberately does not move. The delta this skip declined to
    report is still owed, so the next wake that does fire carries all of it
    rather than starting from a boundary nobody was ever told about.
    """
    with db.lock:
        db.conn.execute(
            "UPDATE lead_heartbeat SET next_due_at=?, quiet_wakes=quiet_wakes+1,"
            " snapshot_hash=? WHERE singleton=1",
            (now, snapshot_hash),
        )
        db.conn.commit()
        row = db.conn.execute(
            "SELECT quiet_wakes FROM lead_heartbeat WHERE singleton=1"
        ).fetchone()
    return 0 if row is None else row["quiet_wakes"]


def post_due_reminder(
    db: Db, now: float, *, sender: str, snapshot: dict, snapshot_hash: str, body_for
) -> tuple | None:
    """Write the reminder and claim it as pending in one transaction.

    This is the whole crash story. Posting first and marking pending second
    leaves a window where a restart sees no pending wake and posts a duplicate;
    marking first and posting second leaves a pending reference to a message
    that does not exist, which mutes the monitor permanently. Doing both in one
    transaction removes the choice: after a crash the reminder either exists
    and is pending, or neither happened. Delivery of a committed message is
    then freely retryable, because the cursor decides when it is settled.

    `body_for` receives the committed row, so the goal that goes into the text
    is the one this generation actually holds — not one read a moment earlier.
    The generation is returned alongside the message: delivery happens after
    this transaction, and must be able to prove it is still delivering for the
    configuration that asked.

    The conditions are also the duplicate guard: concurrent ticks all run this,
    and SQLite lets exactly one of them past ``pending_message_id IS NULL``.
    """
    moment = time.time() if now is None else now
    with db.lock, db.conn:
        row = db.conn.execute(
            "SELECT * FROM lead_heartbeat WHERE singleton=1"
        ).fetchone()
        if row is None:
            return None
        row = dict(row)
        if not row["enabled"] or row["pending_message_id"] is not None:
            return None
        if row["next_due_at"] > moment:
            return None
        # The snapshot is built before this transaction opens, deliberately:
        # reading it needs the same lock this transaction holds, and that lock
        # is not reentrant — building it here deadlocks the tick. Nothing is
        # weakened, because the guard that actually prevents a duplicate is
        # `pending_message_id IS NULL` below, which still admits exactly one of
        # any number of concurrent ticks.
        body = body_for(row, snapshot)
        cursor = db.conn.execute(
            "INSERT INTO messages(conv_id,sender,sender_type,body,created_at)"
            " VALUES(?,?,?,?,?)",
            (row["conv_id"], sender, "system", body, moment),
        )
        message_id = cursor.lastrowid
        # A suspended host can leave the mark many intervals in the past. One
        # reminder is owed, not one per interval missed.
        due = row["next_due_at"] + row["interval_seconds"]
        if due <= moment:
            due = moment + row["interval_seconds"]
        # The snapshot that justified this reminder is recorded with it, in
        # the same transaction: its hash is what a later tick compares against
        # to stay quiet, and `pending_since_id` is the boundary `since_id`
        # advances to once — and only once — the reminder is delivered.
        changed = db.conn.execute(
            "UPDATE lead_heartbeat SET pending_message_id=?, next_due_at=?,"
            " pending_since_id=?, snapshot_hash=?, quiet_wakes=0"
            " WHERE singleton=1 AND generation=? AND pending_message_id IS NULL",
            (message_id, due, snapshot["head_id"], snapshot_hash, row["generation"]),
        )
        if changed.rowcount != 1:  # pragma: no cover - the lock excludes it
            raise RuntimeError("heartbeat row changed inside its own transaction")
    return (
        as_message(
            MessageRow(
                id=message_id,
                conv_id=row["conv_id"],
                sender=sender,
                sender_type="system",
                body=body,
                created_at=moment,
            )
        ),
        row["generation"],
        snapshot,
    )


def settle_delivered(db: Db, *, now: float | None = None) -> dict | None:
    """Clear the pending wake once its owner's cursor has passed the message.

    Delivery is read from the attachment's own durable cursor, which only
    advances when a message has actually been handed over. That is why a
    paste, a broadcast, or elapsed time cannot settle a wake here.
    """
    row = heartbeat.get(db)
    if row is None or row["pending_message_id"] is None:
        return row
    att = db.get_attachment(row["attachment_id"])
    if att is None or att["last_seen"] < row["pending_message_id"]:
        return row
    with db.lock:
        # Delivered at last: the boundary this reminder described is now a
        # boundary the lead has actually seen, so the next delta starts there.
        db.conn.execute(
            "UPDATE lead_heartbeat SET pending_message_id=NULL,"
            " since_id=COALESCE(pending_since_id, since_id), pending_since_id=NULL"
            " WHERE singleton=1 AND pending_message_id=?",
            (row["pending_message_id"],),
        )
        db.conn.commit()
    return heartbeat.get(db)
