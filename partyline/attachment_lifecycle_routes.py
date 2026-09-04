"""Explicit fresh-session and stopped-roster HTTP actions."""

import asyncio
import os

from fastapi import HTTPException, Request

from .attachment_contracts import AttachmentResponse
from .attachment_lifecycle import (FreshAttachmentRequest, create_fresh_record,
                                   remove_stopped_record, require_stopped)
from .contracts import AttachmentEvent, AttachmentRemovedEvent, OkResponse


def register_attachment_lifecycle_routes(app, runtime, *, start, require_loopback, validate):
    @app.post("/api/attachments/{att_id}/fresh", response_model=AttachmentResponse)
    async def fresh_attachment(
        request: Request, att_id: str, body: FreshAttachmentRequest | None = None
    ):
        require_loopback(request)
        body = body or FreshAttachmentRequest()
        att = require_stopped(runtime.db, att_id)
        if att_id in runtime.live:
            raise HTTPException(409, "detach the process before starting fresh")
        try:
            validate(att)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not os.path.isdir(att["cwd"]):
            raise HTTPException(400, "attachment working directory no longer exists")
        replacement = await create_fresh_record(runtime.db, att, body)
        try:
            response = await start(replacement, checkpoint=body.checkpoint, fresh=True)
        except (Exception, asyncio.CancelledError) as exc:
            if replacement["id"] in runtime.live:
                raise HTTPException(500, "fresh start failed; the replacement is still tracked. "
                                    "Detach it before retrying.") from exc
            await runtime.db.set_attachment_status_async(
                replacement["id"], "exited", replacement["runtime_owner"]
            )
            await remove_stopped_record(runtime.db, replacement["id"], missing_ok=True)
            await _removed_event(replacement)
            if isinstance(exc, (HTTPException, asyncio.CancelledError)):
                raise
            raise HTTPException(500, f"failed to start fresh: {exc}") from exc
        await remove_stopped_record(runtime.db, att_id, missing_ok=True)
        await _removed_event(att)
        await runtime.broadcast(att["conv_id"], AttachmentEvent(attachment=response))
        return response


    async def _removed_event(att):
        runtime.uncredited.pop(att["id"], None)
        runtime.unclaimed_noticed.discard(att["id"])
        runtime.reattaching.discard(att["id"])
        await runtime.broadcast(att["conv_id"], AttachmentRemovedEvent(
            attachment_id=att["id"], conversation_id=att["conv_id"],
        ))


    @app.delete("/api/attachments/{att_id}/record", response_model=OkResponse)
    async def remove_attachment_record(request: Request, att_id: str):
        require_loopback(request)
        if att_id in runtime.live:
            raise HTTPException(409, "detach the process before removing it")
        att = await remove_stopped_record(runtime.db, att_id)
        await _removed_event(att)
        return {"ok": True}


