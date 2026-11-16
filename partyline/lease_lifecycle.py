"""What happens around a lease: waking promoted waiters, freeing a settled
task's leases, and telling a job wrapper whether its process holds one.

Promotion itself is database state (`lease_queue.promote_all`), run lazily
wherever leases are touched or read and from the server's existing resource
loop, which also wakes at the earliest expiry that has a waiter behind it — a
deadline computed from the rows, not a timer or a poll. The promoted rows carry
`wake_pending`; each notice is stored once and delivery of that stored notice
is retried until it succeeds.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException, Request

from .auth_guard import request_principal
from .contracts import MessageEvent, MessageResponse
from .mention_relay import LIVE
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


def _store_notice(db, row: dict, conv_id: str, body: str, audience: str) -> None:
    """Persist the one private notice and mark it stored, in a single transaction,
    so an interruption leaves either nothing or a notice that delivery retries."""
    with db.lock, db.conn:
        if not db.conn.execute(
                "SELECT 1 FROM resource_leases WHERE name=? AND holder_attachment=? "
                "AND wake_pending=1", (row["name"], row["holder_attachment"])).fetchone():
            return  # the owner's own poll found the grant meanwhile
        cursor = db.conn.execute(
            "INSERT INTO messages(conv_id,sender,sender_type,body,created_at,"
            "audience_attachment_id) VALUES(?,?,?,?,?,?)",
            (conv_id, "system", "system", body, time.time(), audience))
        db.conn.execute(
            "UPDATE resource_leases SET wake_pending=2, wake_notice_id=? WHERE name=? "
            "AND holder_attachment=? AND wake_pending=1",
            (cursor.lastrowid, row["name"], row["holder_attachment"]))


async def _deliver(runtime, row: dict, att: dict) -> None:
    db = runtime.db
    message = db.message_by_id(att["conv_id"], row["wake_notice_id"])
    if message:
        await runtime.broadcast(att["conv_id"], MessageEvent(
            message=MessageResponse.model_validate(message)))
        await runtime.route_mentions(att["conv_id"], message, force=True)
    db._exec("UPDATE resource_leases SET wake_pending=0 WHERE name=? AND holder_attachment=? "
             "AND wake_pending=2 AND wake_notice_id=?",
             (row["name"], row["holder_attachment"], row["wake_notice_id"]))


async def sweep(runtime) -> int:
    """Promote what the queue rules allow, then wake each promoted process once.

    The notice is stored before it is delivered and cleared only after, so an
    interrupted or failed delivery is retried on the next sweep with the same
    stored message — never lost, never a second copy.
    """
    db = runtime.db
    lock = runtime.__dict__.setdefault("_lease_sweep_lock", asyncio.Lock())
    async with lock:
        await asyncio.to_thread(promote_all, db)
        woken = 0
        while True:
            rows = [dict(row) for row in db._exec(
                "SELECT * FROM resource_leases WHERE waiting=0 AND wake_pending>0 "
                "ORDER BY created_at").fetchall()]
            if not rows:
                return woken
            for row in rows:
                att = db.get_attachment(row["holder_attachment"])
                if att is None or att["status"] not in LIVE:
                    # A promoted waiter that is already gone must not hold the slot.
                    await asyncio.to_thread(release_attachment_leases, db, row["holder_attachment"])
                    continue
                if row["wake_pending"] == 1:
                    await asyncio.to_thread(_store_notice, db, row, att["conv_id"],
                                            f"@{att['name']} {wake_text(row)}", att["id"])
                    row = dict(db._exec(
                        "SELECT * FROM resource_leases WHERE name=? AND holder_attachment=?",
                        (row["name"], row["holder_attachment"])).fetchone() or row)
                if row.get("wake_pending") == 2:
                    await _deliver(runtime, row, att)
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
