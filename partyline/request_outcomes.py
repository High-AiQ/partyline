"""Remember how an approval request ended, and say so when a late caller finds it gone.

A write-set, memory or restart request is deleted once decided, so a second
decision, a withdrawal or a retry after a lost reply used to meet a bare
"no longer pending". The row kept here names the outcome (granted, denied,
approved, declined, withdrawn or expired), who decided, and the reason given.
"""

from __future__ import annotations

import time

from .machine_scope import allows

KEEP_SECONDS = 7 * 24 * 3600
MAX_DETAIL = 500
VERBS = {
    "granted": "granted", "approved": "approved", "denied": "denied", "declined": "declined",
    "withdrawn": "withdrawn", "expired": "expired",
}


def record(db, kind: str, request_id: str, conv_id: str, outcome: str, *,
           actor: str = "", detail: str = "") -> None:
    """Store the outcome. Call it in the same step that removes the request."""
    now = time.time()
    with db.lock, db.conn:
        db.conn.execute("DELETE FROM request_outcomes WHERE resolved_at<?", (now - KEEP_SECONDS,))
        db.conn.execute(
            "INSERT OR REPLACE INTO request_outcomes"
            "(kind,request_id,conv_id,outcome,actor,detail,resolved_at) VALUES(?,?,?,?,?,?,?)",
            (kind, request_id, conv_id, outcome, actor, detail[:MAX_DETAIL], now))


def outcome(db, kind: str, request_id: str) -> dict | None:
    row = db._exec("SELECT * FROM request_outcomes WHERE kind=? AND request_id=?",
                   (kind, request_id)).fetchone()
    return dict(row) if row else None


def not_pending_text(db, kind: str, label: str, request_id: str, principal=None,
                     conv_id: str | None = None) -> str:
    """`that <label> is no longer pending`, plus how it ended when that is known.

    The outcome names a decider and a reason, so it is shown only to a caller
    that may read the line the request was filed on (and, when the route names
    a line, only if the request belonged to it). A caller with no `principal`
    is one the route has already authorized by other means.
    """
    base = f"that {label} is no longer pending"
    found = outcome(db, kind, request_id)
    if found is None:
        return (f"{base}: no outcome is recorded for that id — it may have been replaced, "
                "never filed on this instance, or settled more than a week ago; "
                "read the pending request before acting again")
    if conv_id is not None and found["conv_id"] != conv_id:
        return base
    if principal is not None:
        if not allows(db, principal, found["conv_id"], "read"):
            return base
    verb = VERBS.get(found["outcome"], found["outcome"])
    by = f" by @{found['actor']}" if found["actor"] else ""
    reason = f": {found['detail']}" if found["detail"] else ""
    return f"{base}: it was {verb}{by}{reason}"
