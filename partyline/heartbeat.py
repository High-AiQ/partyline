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

from .db import Db
from .hierarchy import lead_attachment, parent_id_of

DEFAULT_INTERVAL = 900.0
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
    quiet_if_unchanged: bool = True,
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
        # Bootstrap the boundary to the present. Starting at zero would make
        # the first wake a dump of the room's entire history, which is the
        # opposite of a delta.
        head = db.conn.execute("SELECT MAX(id) AS head FROM messages").fetchone()
        since = (head["head"] if head else 0) or 0
        db.conn.execute(
            "INSERT INTO lead_heartbeat("
            "singleton,conv_id,attachment_id,interval_seconds,goal,enabled,"
            "next_due_at,pending_message_id,generation,created_at,"
            "since_id,pending_since_id,snapshot_hash,quiet_wakes,quiet_if_unchanged)"
            " VALUES(1,?,?,?,?,1,?,NULL,1,?,?,NULL,NULL,0,?)"
            " ON CONFLICT(singleton) DO UPDATE SET"
            " conv_id=excluded.conv_id, attachment_id=excluded.attachment_id,"
            " interval_seconds=excluded.interval_seconds, goal=excluded.goal,"
            " enabled=1, next_due_at=excluded.next_due_at, pending_message_id=NULL,"
            " generation=lead_heartbeat.generation+1, since_id=excluded.since_id,"
            " pending_since_id=NULL, snapshot_hash=NULL, quiet_wakes=0,"
            " quiet_if_unchanged=excluded.quiet_if_unchanged",
            (conv_id, attachment_id, interval, text, moment + interval, moment,
             since, 1 if quiet_if_unchanged else 0),
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


def held(db: Db, row: dict | None) -> bool:
    """Is that row still somebody's monitor?

    A row outlives its owner on purpose (`disable` keeps it so the interval
    and goal survive), but a disabled row, or one whose attachment is no
    longer the root manager of its line, guards nothing. Treating it as
    owned locked every later root captain out of the endpoint with "belongs
    to another line's manager" — for a monitor that was off, on a line whose
    process had long since been deleted.
    """
    if row is None or not row["enabled"]:
        return False
    return is_root_lead(db, row["conv_id"], row["attachment_id"])


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
            "since_id": 0,
            "snapshot_hash": None,
            "quiet_wakes": 0,
            "quiet_if_unchanged": True,
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
        "since_id": row["since_id"],
        "snapshot_hash": row["snapshot_hash"],
        "quiet_wakes": row["quiet_wakes"],
        "quiet_if_unchanged": bool(row["quiet_if_unchanged"]),
    }
