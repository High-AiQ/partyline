"""Per-attachment requests to raise a process memory cap."""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .adapters import ADAPTER_METADATA
from .approval_bubble import broadcast_approval_change, bubble_approval
from .auth_guard import request_principal
from .memory_live_raise import raise_live
from .machine_scope import deny_unless, is_human
from .memory_contracts import MemoryRequestEvent
from .resume_continuation import resume_with_backlog
from .mention_relay import post_private
from .process_memory import parse_size
from .restart_capabilities import adapter_can_resume
from .resource_budget import cap_bytes, memory_ceiling, settings
from .system_notice import post_system_notice


class MemoryRequestIn(BaseModel):
    requested_limit: str = Field(pattern=r"^[1-9][0-9]{0,5}[KMG]$")
    reason: str = Field(min_length=1, max_length=2000)


def _pending(db, conv_id: str) -> dict | None:
    row = db._exec("SELECT * FROM memory_limit_requests WHERE conv_id=? AND expired_at IS NULL "
                   "ORDER BY created_at LIMIT 1",
                   (conv_id,)).fetchone()
    return dict(row) if row else None


async def expire_memory_requests(runtime, att_id: str) -> None:
    """A detached worker cannot be resumed with a bigger cap: stop offering Approve."""
    db = runtime.db
    with db.lock, db.conn:
        rows = db.conn.execute(
            "UPDATE memory_limit_requests SET expired_at=? WHERE attachment_id=? "
            "AND expired_at IS NULL RETURNING conv_id", (time.time(), att_id)).fetchall()
    for conv_id in {row["conv_id"] for row in rows}:
        await runtime.broadcast(conv_id, MemoryRequestEvent(request=_pending(db, conv_id)))
        await broadcast_approval_change(runtime, conv_id)


async def _queue_memory_continuation(runtime, att, limit):
    """An idle resumed CLI still needs an addressed wake to continue its work."""
    from .orchestrator_store import attachment_task

    row = attachment_task(runtime.db, att['id'])
    action = 'continue your current work'
    state = ''
    if row:
        action = 'continue the task'
        if row['status'] in ('approved', 'done'):
            action = 'wait for the root captain to reopen the task before starting new work'
        elif row['status'] == 'in_review' and att['id'] == row['implementer_id']:
            action = 'wait for the current review verdict'
        state = (f" Current task state: {row['status']}, round {row['round']}, "
                 f"SHA {row['sha'] or 'none'}.")
    await post_private(
        runtime, att['conv_id'], 'system', 'system',
        f'You were restarted with a new memory cap ({limit}); {action}.' + state,
        audience=att['id'], route=False)


async def _restart_with_cap(runtime, resume, att, current, announce) -> bool:
    """Fallback: detach, record the cap and resume. False when the resume failed."""
    from .line_process_routes import detach_attachment
    db = runtime.db
    if att["id"] in runtime.live:
        await detach_attachment(runtime, att["id"], survivors=False, expire=False)
    with db.lock, db.conn:
        db.conn.execute("UPDATE attachments SET memory_limit=? WHERE id=?",
                        (current["requested_limit"], att["id"]))
    runtime.reattaching.add(att["id"])
    try:
        await _queue_memory_continuation(runtime, att, current["requested_limit"])
        await resume_with_backlog(runtime, att["id"], resume)
    except Exception as exc:
        text = (f"☏ memory cap for @{att['name']} is now {current['requested_limit']}, "
                f"but resume failed ({exc}); request remains open and the process is "
                "stopped. Retry approval or resume it manually.")
        try:
            await announce(current["conv_id"], text)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("could not announce memory resume failure")
        return False
    finally:
        runtime.reattaching.discard(att["id"])
    return True


def register_memory_request_routes(app: FastAPI, runtime, resume) -> None:
    db = runtime.db

    async def announce(conv_id: str, message: str) -> None:
        await post_system_notice(runtime, conv_id, message)
        await runtime.broadcast(conv_id, MemoryRequestEvent(request=_pending(db, conv_id)))
        await broadcast_approval_change(runtime, conv_id)

    @app.get("/api/conversations/{conv_id}/memory-request")
    async def pending(request: Request, conv_id: str):
        deny_unless(db, request_principal(request), conv_id, "read")
        return {"request": _pending(db, conv_id)}

    @app.post("/api/attachments/{att_id}/memory-requests")
    async def file(request: Request, att_id: str, body: MemoryRequestIn):
        actor = request_principal(request)
        att = db.get_attachment(att_id)
        if att is None:
            raise HTTPException(404)
        if actor.kind == "machine" and actor.attachment_id != att_id:
            deny_unless(db, actor, att["conv_id"], "assign")
        amount = parse_size(body.requested_limit)
        reason = body.reason.strip()
        if not reason:
            raise HTTPException(422, "reason cannot be blank")
        ceiling = memory_ceiling()
        if amount > ceiling:
            raise HTTPException(400, f"requested limit exceeds the host ceiling of {ceiling} bytes")
        if amount <= cap_bytes(att, settings(db)):
            raise HTTPException(409, "requested memory limit must be higher than the current cap")
        if amount <= 0:
            raise HTTPException(422, "requested limit must be positive")
        if _pending(db, att["conv_id"]):
            raise HTTPException(409, "a memory request is already pending on this line")
        with db.lock, db.conn:
            db.conn.execute("DELETE FROM memory_limit_requests WHERE conv_id=? "
                            "AND expired_at IS NOT NULL", (att["conv_id"],))
        ident = uuid.uuid4().hex[:12]
        record = {"id": ident, "attachment_id": att_id, "conv_id": att["conv_id"],
                  "requester": actor.name, "requester_attachment_id": actor.attachment_id,
                  "requested_limit": body.requested_limit,
                  "reason": reason, "created_at": time.time()}
        with db.lock, db.conn:
            db.conn.execute(
                "INSERT INTO memory_limit_requests(id,attachment_id,conv_id,requester,"
                "requester_attachment_id,requested_limit,reason,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (ident, att_id, att["conv_id"], actor.name, actor.attachment_id,
                 body.requested_limit, record["reason"], record["created_at"]))
        await announce(att["conv_id"],
                       f"☏ @{actor.name} requests a {body.requested_limit} memory cap for "
                       f"@{att['name']}: {record['reason']} — review the request banner")
        await bubble_approval(
            runtime, att["conv_id"], kind="memory", requester=actor.name,
            detail=f"{body.requested_limit} memory cap for @{att['name']}: {reason}",
            approve=f"POST /api/memory-requests/{ident}/approve",
            decline=f"DELETE /api/memory-requests/{ident}",
            actor=actor,
        )
        return record

    def take(request: Request, request_id: str, *, approving: bool):
        actor = request_principal(request)
        row = db._exec("SELECT * FROM memory_limit_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "memory request is no longer pending")
        current = dict(row)
        if approving and current["expired_at"] is not None:
            raise HTTPException(
                410, "worker gone: its process was detached or its line retired, so this "
                     "request expired; decline it to clear it and file a new one if needed")
        # The requester is refused only when it filed for itself; a captain may
        # approve a request it filed for another process within its scope.
        if (actor.kind == "machine" and actor.attachment_id == current["requester_attachment_id"]
                and current["requester_attachment_id"] == current["attachment_id"]):
            raise HTTPException(403, "a process cannot approve its own memory request")
        if (approving and actor.kind == "machine"
                and actor.attachment_id == current["attachment_id"]):
            raise HTTPException(403, "a process cannot approve its own memory limit")
        if is_human(actor):
            return current, actor
        deny_unless(db, actor, current["conv_id"], "assign")
        if (approving and parse_size(current["requested_limit"])
                > settings(db)["memory_captain_ceiling_bytes"]):
            raise HTTPException(
                403, "this request exceeds the captain approval ceiling; a person must decide"
            )
        return current, actor

    @app.post("/api/memory-requests/{request_id}/approve")
    async def approve(request: Request, request_id: str):
        current, actor = take(request, request_id, approving=True)
        att = db.get_attachment(current["attachment_id"])
        if att is None:
            raise HTTPException(410, "worker gone: its attachment was removed")
        limit = current["requested_limit"]
        live = att["id"] in runtime.live and await raise_live(runtime, att["id"], limit)
        if live:
            with db.lock, db.conn:
                db.conn.execute("UPDATE attachments SET memory_limit=? WHERE id=?",
                                (limit, att["id"]))
        else:
            if not adapter_can_resume(ADAPTER_METADATA.get(att["adapter"], {})):
                raise HTTPException(409, f"@{att['name']} uses an adapter that cannot resume")
            if not await _restart_with_cap(runtime, resume, att, current, announce):
                return {"request": _pending(db, current["conv_id"]), "resume_failed": True}
        with db.lock, db.conn:
            db.conn.execute("DELETE FROM memory_limit_requests WHERE id=?", (request_id,))
        text = (f"☏ memory request for @{att['name']} approved by @{actor.name}; "
                f"new cap {limit} is active "
                f"({'applied to the running process, no restart' if live else 'process restarted'})")
        await announce(current["conv_id"], text)
        if current["requester_attachment_id"]:
            target = db.get_attachment(current["requester_attachment_id"])
            if target:
                await post_private(runtime, target["conv_id"], "system", "system", text,
                                   audience=target["id"], actor=actor)
        return {"request": _pending(db, current["conv_id"])}

    @app.delete("/api/memory-requests/{request_id}")
    async def deny(request: Request, request_id: str):
        current, actor = take(request, request_id, approving=False)
        att = db.get_attachment(current["attachment_id"])
        with db.lock, db.conn:
            db.conn.execute("DELETE FROM memory_limit_requests WHERE id=?", (request_id,))
        await announce(current["conv_id"],
                       f"☏ memory request for @{att['name'] if att else current['attachment_id']} "
                       f"declined by @{actor.name}")
        return {"request": _pending(db, current["conv_id"])}
