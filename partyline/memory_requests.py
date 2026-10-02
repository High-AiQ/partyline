"""Per-attachment requests to raise a process memory cap."""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .auth_guard import request_principal
from .adapters import ADAPTER_METADATA
from .machine_scope import deny_unless, is_human
from .memory_contracts import MemoryRequestEvent
from .resume_continuation import resume_with_backlog
from .mention_relay import post_private
from .process_memory import parse_size
from .reattach import adapter_can_resume
from .resource_budget import cap_bytes, memory_ceiling, settings
from .system_notice import post_system_notice


class MemoryRequestIn(BaseModel):
    requested_limit: str = Field(pattern=r"^[1-9][0-9]{0,5}[KMG]$")
    reason: str = Field(min_length=1, max_length=2000)


def _pending(db, conv_id: str) -> dict | None:
    row = db._exec("SELECT * FROM memory_limit_requests WHERE conv_id=? ORDER BY created_at LIMIT 1",
                   (conv_id,)).fetchone()
    return dict(row) if row else None


def register_memory_request_routes(app: FastAPI, runtime, resume) -> None:
    db = runtime.db

    async def announce(conv_id: str, message: str) -> None:
        await post_system_notice(runtime, conv_id, message)
        await runtime.broadcast(conv_id, MemoryRequestEvent(request=_pending(db, conv_id)))

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
            deny_unless(db, actor, att["conv_id"], "attach")
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
        ident = uuid.uuid4().hex[:12]
        record = {"id": ident, "attachment_id": att_id, "conv_id": att["conv_id"],
                  "requester": actor.name, "requester_attachment_id": actor.attachment_id,
                  "requested_limit": body.requested_limit,
                  "reason": reason, "created_at": time.time()}
        with db.lock, db.conn:
            db.conn.execute(
                "INSERT INTO memory_limit_requests VALUES(?,?,?,?,?,?,?,?)",
                (ident, att_id, att["conv_id"], actor.name, actor.attachment_id,
                 body.requested_limit, record["reason"], record["created_at"]))
        await announce(att["conv_id"],
                       f"☏ @{actor.name} requests a {body.requested_limit} memory cap for "
                       f"@{att['name']}: {record['reason']} — review the request banner")
        return record

    def take(request: Request, request_id: str, *, approving: bool):
        actor = request_principal(request)
        row = db._exec("SELECT * FROM memory_limit_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "memory request is no longer pending")
        current = dict(row)
        if actor.kind == "machine" and actor.attachment_id == current["requester_attachment_id"]:
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
            raise HTTPException(404, "attachment was removed")
        if not adapter_can_resume(ADAPTER_METADATA.get(att["adapter"], {})):
            raise HTTPException(409, f"@{att['name']} uses an adapter that cannot resume")
        from .line_process_routes import detach_attachment
        if att["id"] in runtime.live:
            await detach_attachment(runtime, att["id"])
        with db.lock, db.conn:
            db.conn.execute("UPDATE attachments SET memory_limit=? WHERE id=?",
                            (current["requested_limit"], att["id"]))
        runtime.reattaching.add(att["id"])
        try:
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
            return {"request": _pending(db, current["conv_id"]), "resume_failed": True}
        finally:
            runtime.reattaching.discard(att["id"])
        with db.lock, db.conn:
            db.conn.execute("DELETE FROM memory_limit_requests WHERE id=?", (request_id,))
        text = (f"☏ memory request for @{att['name']} approved by @{actor.name}; "
                f"new cap {current['requested_limit']} is active")
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
