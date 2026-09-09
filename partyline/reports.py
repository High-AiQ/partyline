"""Parent-pulled child reports.

Writing a report never routes a mention. A report marked ``notify`` asks for
one wake of the parent's manager, and that wake is a separate fact from the
report being stored:

* ``notified_at IS NULL`` — stored, nobody told yet. Either no manager is
  appointed on the parent, or delivering the wake failed. The next escalation
  from this child retries it.
* ``notifying_at`` set — a wake is being delivered right now. Concurrent
  escalations see the claim and stay quiet rather than each waking the
  manager. The claim is released on failure and expires on a lease, so a
  caller that dies mid-delivery cannot hold it for ever.
* ``notified_at`` set — the manager was woken. Further escalations coalesce
  into the same row, bumping ``revision``, and stay quiet until it is
  acknowledged.

Collapsing those two into one flag is what muted a child indefinitely: a
notify with no manager left a pending row, and the unique index then used that
row to suppress every wake that followed.

The table lives in ``db_schema.MIGRATIONS``. It used to be created on first
use, and running `executescript` per request committed the shared connection
out from under cursors other threads were still reading — an
``InterfaceError`` under concurrent posts.
"""

from __future__ import annotations

import sqlite3
import time

from .db import Db

MAX_BODY = 2000
# How long a wake may be in flight before another escalation may take it over.
# A caller that dies mid-delivery would otherwise hold the claim for good, and
# the row it holds is the one thing standing between this child and silence.
NOTIFY_CLAIM_SECONDS = 30.0


def wake_message(lead_name: str, report_id: int) -> str:
    """Fixed pointer to the inbox row. Never interpolates report text or names."""
    return f"@{lead_name} needs attention: report {report_id}"


class ReportError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _row(conn, report_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM line_reports WHERE id=?", (report_id,)
    ).fetchone()
    if row is None:
        raise ReportError(404, f"no report #{report_id}")
    return dict(row)


def _pending(conn, parent_conv_id: str, child_conv_id: str):
    """This child's unacknowledged notify, whether or not it was delivered."""
    return conn.execute(
        "SELECT * FROM line_reports WHERE parent_conv_id=? AND child_conv_id=?"
        " AND notify=1 AND acknowledged_at IS NULL",
        (parent_conv_id, child_conv_id),
    ).fetchone()


def add(
    db: Db,
    parent_conv_id: str,
    child_conv_id: str,
    author: str,
    body: str,
    *,
    author_attachment_id: str | None = None,
    notify: bool = False,
) -> tuple[dict, bool]:
    """Store a report. Second value is True when a parent wake should fire.

    True whenever no *delivered* wake is outstanding — so an escalation that
    was stored but never announced is retried rather than swallowed.
    """
    text = body.strip()
    if not text or len(text) > MAX_BODY:
        raise ReportError(400, f"body must be 1-{MAX_BODY} characters")
    now = time.time()
    with db.lock:
        if notify:
            return _upsert_notify(
                db.conn,
                parent_conv_id,
                child_conv_id,
                author,
                author_attachment_id,
                text,
                now,
            )
        cursor = db.conn.execute(
            "INSERT INTO line_reports("
            "parent_conv_id,child_conv_id,author,author_attachment_id,"
            "body,notify,revision,created_at) VALUES(?,?,?,?,?,?,1,?)",
            (
                parent_conv_id,
                child_conv_id,
                author,
                author_attachment_id,
                text,
                0,
                now,
            ),
        )
        db.conn.commit()
        return _row(db.conn, cursor.lastrowid), False


def _claim_wake(conn, report_id: int, now: float) -> bool:
    """Take the one outstanding wake for this row, if it is free to take."""
    changed = conn.execute(
        "UPDATE line_reports SET notifying_at=? WHERE id=? AND notified_at IS NULL"
        " AND (notifying_at IS NULL OR notifying_at <= ?)",
        (now, report_id, now - NOTIFY_CLAIM_SECONDS),
    )
    return changed.rowcount == 1


def _upsert_notify(conn, parent, child, author, author_att, text, now):
    """One pending notify per child. Coalesce bumps revision.

    A wake is asked for again only while the outstanding row has never been
    delivered; once the manager has been told, later escalations are quiet
    until the acknowledgement.
    """
    for _ in range(4):
        existing = _pending(conn, parent, child)
        if existing is not None:
            changed = conn.execute(
                "UPDATE line_reports SET body=?, author=?, author_attachment_id=?,"
                " revision=revision+1 WHERE id=? AND acknowledged_at IS NULL",
                (text, author, author_att, existing["id"]),
            )
            conn.commit()
            if changed.rowcount == 1:
                wake = _claim_wake(conn, existing["id"], now)
                conn.commit()
                return _row(conn, existing["id"]), wake
            continue
        try:
            cursor = conn.execute(
                "INSERT INTO line_reports("
                "parent_conv_id,child_conv_id,author,author_attachment_id,"
                "body,notify,revision,notifying_at,created_at) VALUES(?,?,?,?,?,1,1,?,?)",
                (parent, child, author, author_att, text, now, now),
            )
            conn.commit()
            return _row(conn, cursor.lastrowid), True
        except sqlite3.IntegrityError:
            conn.rollback()
    raise ReportError(409, "could not coalesce the pending notify")


def release_wake_claim(db: Db, report_id: int, claim: float | None) -> dict:
    """Give back *this* caller's wake, so the next escalation retries it.

    Fenced on the claim value. An attempt whose lease expired can still return
    late, and an unfenced release would hand away a claim that now belongs to
    a newer attempt — waking the manager twice, or clearing a wake that is
    about to be delivered.
    """
    with db.lock:
        db.conn.execute(
            "UPDATE line_reports SET notifying_at=NULL"
            " WHERE id=? AND notified_at IS NULL AND notifying_at IS ?",
            (report_id, claim),
        )
        db.conn.commit()
        return _row(db.conn, report_id)


def mark_notified(db: Db, report_id: int, claim: float | None) -> dict:
    """Record that the parent's manager was actually woken for this report.

    Called only after the wake has been posted, and fenced on the same claim
    value: a late attempt must not complete a wake it no longer owns. Until
    the row is marked, it stays retryable, which is what makes a failed or
    undeliverable escalation recoverable instead of silently final.
    """
    with db.lock:
        db.conn.execute(
            "UPDATE line_reports SET notified_at=?, notifying_at=NULL"
            " WHERE id=? AND notified_at IS NULL AND notifying_at IS ?",
            (time.time(), report_id, claim),
        )
        db.conn.commit()
        return _row(db.conn, report_id)


def acknowledge(db: Db, report_id: int, parent_conv_id: str, revision: int) -> dict:
    with db.lock:
        row = _row(db.conn, report_id)
        if row["parent_conv_id"] != parent_conv_id:
            raise ReportError(404, f"no report #{report_id}")
        if row["acknowledged_at"] is not None:
            raise ReportError(409, "report already acknowledged")
        changed = db.conn.execute(
            "UPDATE line_reports SET acknowledged_at=? "
            "WHERE id=? AND revision=? AND acknowledged_at IS NULL",
            (time.time(), report_id, revision),
        )
        db.conn.commit()
        if changed.rowcount != 1:
            raise ReportError(
                409, "report was updated; read it again before acknowledging"
            )
        return _row(db.conn, report_id)


def get(db: Db, report_id: int) -> dict:
    with db.lock:
        return _row(db.conn, report_id)


def list_for_parent(db: Db, parent_conv_id: str) -> list[dict]:
    rows = db._exec(
        "SELECT * FROM line_reports WHERE parent_conv_id=? ORDER BY id",
        (parent_conv_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def purge_conversation(db: Db, conv_id: str) -> None:
    db._exec(
        "DELETE FROM line_reports WHERE parent_conv_id=? OR child_conv_id=?",
        (conv_id, conv_id),
    )
