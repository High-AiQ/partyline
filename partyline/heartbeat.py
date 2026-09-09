"""An opt-in timer that reminds the root manager to work its inbox.

A lead can stall a whole tree quietly: children file reports, nobody pulls
them, and every process sits idle looking correct. Nothing in the room says so,
because silence is what a healthy line looks like too. This is the heart
monitor the root lead straps on for a goal it intends to finish — its own
choice, its own line, and its own to remove.

Three properties make it a monitor rather than another source of noise:

* **One pending wake, ever.** A second reminder is never posted while the first
  is unanswered, so a lead that is deep in work does not return to a backlog of
  identical nags.
* **A wake settles on delivery, not on posting.** Pasting text at a process is
  not evidence it arrived; the cursor advancing past that message is. Settling
  on the paste would let a wedged adapter be reminded forever without ever
  receiving anything.
* **It authorizes nothing.** The reminder is a pointer to work already owned.
  It never carries budget, and it never speaks for the lead.

The row is a singleton because the root line is: one tree, one root manager,
one monitor. Disabling keeps the row and clears the flag, so the interval and
goal a lead chose survive being switched off and on again — and so completion
is always an explicit act, never a timer that quietly decided it was done.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .db import Db, MessageRow
from .hierarchy import lead_attachment, parent_id_of
from .message_queries import as_message

DEFAULT_INTERVAL = 300.0
# A minute is the floor because the reminder competes with the lead's actual
# turn; anything faster is a denial of service dressed as diligence. An hour is
# the ceiling because past that the monitor cannot notice a stall worth
# noticing, and a lead who wants that should just disable it.
MIN_INTERVAL = 60.0
MAX_INTERVAL = 3600.0

DEFAULT_GOAL = (
    "review child reports, unblock the next step for each line, "
    "and disable this heartbeat when the goal is met"
)
MAX_GOAL = 500


class HeartbeatError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def wake_body(name: str, goal: str) -> str:
    """The reminder itself: a mention, a pointer, and no authority.

    Fixed shape on purpose. This text is posted by the server on a schedule
    nobody is watching, so it must never be able to read as an instruction
    from a person, and it must never imply permission the lead does not
    already hold.
    """
    return (
        f"@{name} heartbeat: {goal}. "
        "No reply is needed if nothing is waiting. "
        "This reminder authorizes no spending, rendering, or deployment."
    )


def normalize_interval(seconds: float | None) -> float:
    if seconds is None:
        return DEFAULT_INTERVAL
    try:
        value = float(seconds)
    except (TypeError, ValueError) as exc:
        raise HeartbeatError(400, "interval_seconds must be a number") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise HeartbeatError(400, "interval_seconds must be a number")
    if not MIN_INTERVAL <= value <= MAX_INTERVAL:
        raise HeartbeatError(
            400, f"interval_seconds must be {MIN_INTERVAL:g}-{MAX_INTERVAL:g}"
        )
    return value


def normalize_goal(goal: str | None) -> str:
    text = (goal or DEFAULT_GOAL).strip()
    if not text or len(text) > MAX_GOAL:
        raise HeartbeatError(400, f"goal must be 1-{MAX_GOAL} characters")
    return text


def is_root_lead(db: Db, conv_id: str | None, attachment_id: str | None) -> bool:
    """Only the manager of the top line, and only while it still is one."""
    if not conv_id or not attachment_id:
        return False
    conv = db.get_conversation(conv_id)
    if conv is None or parent_id_of(conv) is not None:
        return False
    lead = lead_attachment(db, conv_id)
    return lead is not None and lead["id"] == attachment_id


def get(db: Db) -> dict | None:
    row = db._exec("SELECT * FROM lead_heartbeat WHERE singleton=1").fetchone()
    return dict(row) if row is not None else None


def enable(
    db: Db,
    conv_id: str,
    attachment_id: str,
    *,
    interval_seconds: float | None = None,
    goal: str | None = None,
    now: float | None = None,
) -> dict:
    """Start or re-point the monitor at the caller's own attachment.

    Enabling always names the caller as owner — there is no parameter for
    whose process gets woken, because a timer that can be aimed at another
    process is a way to nag someone else on a schedule.

    Every enable bumps ``generation``. Disabling and re-enabling with the same
    interval, from the same attachment, still produces a configuration that
    anything already in flight can be told apart from.
    """
    interval = normalize_interval(interval_seconds)
    text = normalize_goal(goal)
    moment = time.time() if now is None else now
    with db.lock:
        db.conn.execute(
            "INSERT INTO lead_heartbeat("
            "singleton,conv_id,attachment_id,interval_seconds,goal,enabled,"
            "next_due_at,pending_message_id,generation,created_at)"
            " VALUES(1,?,?,?,?,1,?,NULL,1,?)"
            " ON CONFLICT(singleton) DO UPDATE SET"
            " conv_id=excluded.conv_id, attachment_id=excluded.attachment_id,"
            " interval_seconds=excluded.interval_seconds, goal=excluded.goal,"
            " enabled=1, next_due_at=excluded.next_due_at, pending_message_id=NULL,"
            " generation=lead_heartbeat.generation+1",
            (conv_id, attachment_id, interval, text, moment + interval, moment),
        )
        db.conn.commit()
    return get(db)


def disable(db: Db) -> dict | None:
    """Stop reminding, and forget the outstanding one.

    The row survives so the next enable keeps the interval and goal that were
    already chosen, and so `status` can still answer "off" rather than
    "never configured".
    """
    with db.lock:
        db.conn.execute(
            "UPDATE lead_heartbeat SET enabled=0, pending_message_id=NULL,"
            " generation=generation+1 WHERE singleton=1"
        )
        db.conn.commit()
    return get(db)


def owns(row: dict | None, conv_id: str | None, attachment_id: str | None) -> bool:
    """Is this the attachment whose monitor that row is?

    There can be more than one root line in a database, so "a root manager" is
    not the same question as "this monitor's manager". Without this, one root
    lead could read, re-point, or switch off another's.
    """
    if row is None:
        return False
    return row["conv_id"] == conv_id and row["attachment_id"] == attachment_id


def status(db: Db, *, now: float | None = None) -> dict:
    row = get(db)
    if row is None:
        return {
            "enabled": False,
            "conv_id": None,
            "attachment_id": None,
            "interval_seconds": DEFAULT_INTERVAL,
            "goal": None,
            "next_due_at": None,
            "seconds_until_due": None,
            "wake_pending": False,
            "pending_message_id": None,
        }
    moment = time.time() if now is None else now
    pending = row["pending_message_id"]
    return {
        "enabled": bool(row["enabled"]),
        "conv_id": row["conv_id"],
        "attachment_id": row["attachment_id"],
        "interval_seconds": row["interval_seconds"],
        "goal": row["goal"],
        "next_due_at": row["next_due_at"] if row["enabled"] else None,
        "seconds_until_due": (
            max(0.0, row["next_due_at"] - moment) if row["enabled"] else None
        ),
        "wake_pending": pending is not None,
        "pending_message_id": pending,
    }


def post_due_reminder(
    db: Db, now: float, *, sender: str, body_for: Callable[[dict], str]
) -> tuple[MessageRow, int] | None:
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
        body = body_for(row)
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
        changed = db.conn.execute(
            "UPDATE lead_heartbeat SET pending_message_id=?, next_due_at=?"
            " WHERE singleton=1 AND generation=? AND pending_message_id IS NULL",
            (message_id, due, row["generation"]),
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
    )


def settle_delivered(db: Db, *, now: float | None = None) -> dict | None:
    """Clear the pending wake once its owner's cursor has passed the message.

    Delivery is read from the attachment's own durable cursor, which only
    advances when a message has actually been handed over. That is why a
    paste, a broadcast, or elapsed time cannot settle a wake here.
    """
    row = get(db)
    if row is None or row["pending_message_id"] is None:
        return row
    att = db.get_attachment(row["attachment_id"])
    if att is None or att["last_seen"] < row["pending_message_id"]:
        return row
    with db.lock:
        db.conn.execute(
            "UPDATE lead_heartbeat SET pending_message_id=NULL"
            " WHERE singleton=1 AND pending_message_id=?",
            (row["pending_message_id"],),
        )
        db.conn.commit()
    return get(db)
