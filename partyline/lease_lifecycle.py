"""What happens around a lease: waking promoted waiters, freeing a settled
task's leases, and telling a job wrapper whether its process holds one.

Promotion itself is database state (`resource_leases.promote_all`), run lazily
wherever leases are touched or read and from the server's existing resource
loop, which also wakes at the earliest expiry that has a waiter behind it — a
deadline computed from the rows, not a timer or a poll. The promoted rows carry
`wake_pending`; delivery claims each flag once, so a notice is never doubled.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException, Request

from .auth_guard import request_principal
from .mention_relay import LIVE, post_private
from .resource_leases import (
    LEASE_NAME,
    MAX_TTL_S,
    promote_all,
    release_attachment_leases,
)


def holds_lease(db, holder_attachment: str) -> bool:
    """Whether the process holds a granted, unexpired lease (a queued place is not one)."""
    return bool(db._exec(
        "SELECT 1 FROM resource_leases WHERE holder_attachment=? AND waiting=0 "
        "AND expires_at>? LIMIT 1", (holder_attachment, time.time())).fetchone())


def holder_status(db, name: str, holder_attachment: str) -> dict:
    """Does this process hold lease ``name``? ``state`` is held, waiting or none."""
    promote_all(db)
    row = db._exec("SELECT * FROM resource_leases WHERE name=? AND holder_attachment=?",
                   (name, holder_attachment)).fetchone()
    state = "none" if row is None else "waiting" if row["waiting"] else "held"
    return {"name": name, "attachment": holder_attachment, "held": state == "held",
            "state": state, "mode": row["mode"] if row else "",
            "expires_at": row["expires_at"] if state == "held" else 0}


def wake_text(row: dict) -> str:
    ttl = min(row.get("ttl_s") or MAX_TTL_S, MAX_TTL_S)
    return (f"lease «{row['name']}» is now granted to you ({row['mode']}, ttl {ttl}s). "
            f"Start your job; release it with DELETE /api/leases/{row['name']} when done.")


async def sweep(runtime) -> int:
    """Promote what the queue rules allow, then wake each promoted process once."""
    db = runtime.db
    await asyncio.to_thread(promote_all, db)
    woken = 0
    while True:
        rows = [dict(row) for row in db._exec(
            "SELECT * FROM resource_leases WHERE waiting=0 AND wake_pending=1").fetchall()]
        if not rows:
            return woken
        for row in rows:
            key = (row["name"], row["holder_attachment"])
            claimed = db._exec(
                "UPDATE resource_leases SET wake_pending=0 WHERE name=? AND "
                "holder_attachment=? AND wake_pending=1", key).rowcount
            if not claimed:
                continue
            att = db.get_attachment(row["holder_attachment"])
            if att is None or att["status"] not in LIVE:
                # A promoted waiter that is already gone must not hold the slot.
                await asyncio.to_thread(release_attachment_leases, db, row["holder_attachment"])
                continue
            try:
                await post_private(runtime, att["conv_id"], "system", "system",
                                   f"@{att['name']} {wake_text(row)}", audience=att["id"])
            except BaseException:
                db._exec("UPDATE resource_leases SET wake_pending=1 WHERE name=? AND "
                         "holder_attachment=?", key)
                raise
            woken += 1


def next_expiry_delay(db, now: float | None = None) -> float | None:
    """Seconds until the earliest granted lease that has a waiter behind it expires."""
    now = time.time() if now is None else now
    row = db._exec(
        "SELECT MIN(h.expires_at) FROM resource_leases h WHERE h.waiting=0 AND EXISTS "
        "(SELECT 1 FROM resource_leases w WHERE w.name=h.name AND w.waiting=1)").fetchone()
    return None if row[0] is None else max(0.0, row[0] - now)


def holds_any_lease(db, attachment_id: str) -> bool:
    """A granted, unexpired lease or captain-declared resource: legitimate long work,
    so idle and stall detection leave the process alone. A queue place is not one."""
    try:
        if holds_lease(db, attachment_id):
            return True
        return bool(db._exec(
            "SELECT 1 FROM line_resource_claims WHERE attachment_id=? AND granted_at IS NOT NULL "
            "LIMIT 1", (attachment_id,)).fetchone())
    except Exception:
        return False  # a minimal db without the lease tables holds none


async def release_for_task(runtime, row: dict) -> list[str]:
    """Free every lease the settled task's implementer and reviewer hold, so approval
    never leaves a slot behind and nobody has to message the task to release it."""
    db = runtime.db
    ids = [ident for ident in (row.get("implementer_id"), row.get("reviewer_id")) if ident]
    names: list[str] = []
    for ident in ids:
        names += [r[0] for r in db._exec(
            "SELECT name FROM resource_leases WHERE holder_attachment=? AND waiting=0",
            (ident,)).fetchall()]
        names += [r[0] for r in db._exec(
            "SELECT name FROM line_resource_claims WHERE attachment_id=? AND granted_at IS NOT NULL",
            (ident,)).fetchall()]
        await asyncio.to_thread(release_attachment_leases, db, ident)
        db._exec("DELETE FROM line_resource_claims WHERE attachment_id=?", (ident,))
    if ids:
        from .line_resource_routes import maintain
        await maintain(runtime)
    await sweep(runtime)
    return sorted(set(names))


def register_holder_route(app, runtime) -> None:
    @app.get("/api/leases/{name}/holder")
    async def lease_holder(name: str, request: Request, attachment: str | None = None):
        """For a job wrapper: does this process (or ``attachment``) hold lease ``name``?"""
        principal = request_principal(request)
        who = attachment or principal.attachment_id
        if not who:
            raise HTTPException(422, "name the process with ?attachment=<id>")
        if not LEASE_NAME.fullmatch(name):
            raise HTTPException(422, "lease name must be 1-64 letters, digits, dots, dashes")
        result = await asyncio.to_thread(holder_status, runtime.db, name, who)
        await sweep(runtime)  # an expiry this read found wakes its waiter now
        return result
