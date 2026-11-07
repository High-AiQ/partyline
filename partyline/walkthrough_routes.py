"""Owner-only controls and final upload for ephemeral walkthrough takes."""

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth_guard import request_principal
from .contracts import MessageEvent, MessageResponse
from .idempotent_posts import claim_key, original_for_key, principal_identity, remember_key
from .machine_scope import deny_unless, is_human
from .media_digest import digest_body
from .media_files import prepared_file
from .media_images import MediaError
from .screen_routes import _mark_pointer, pointer_coordinates
from .walkthrough import assemble_message, select_frames


class Segment(BaseModel):
    start: float = Field(ge=0, le=3600, allow_inf_nan=False)
    end: float = Field(ge=0, le=3600, allow_inf_nan=False)
    text: str = Field(max_length=10000)


class Finish(BaseModel):
    notes: str = Field(default="", max_length=50000)
    segments: list[Segment] = Field(default_factory=list, max_length=5000)
    transcription_error: bool = False
    mark_pointer: bool = False


def walkthrough_router(runtime, hub, store):
    router = APIRouter()

    def owned(request, conv_id, share_id):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "write")
        take = hub.walkthroughs.items.get(share_id)
        if (not is_human(principal) or not take or take.owner_id != principal.user_id
                or take.conv_id != conv_id):
            raise HTTPException(404, "walkthrough not found")
        return principal, take

    @router.post("/api/conversations/{conv_id}/walkthroughs/{share_id}/arm")
    async def arm(conv_id: str, share_id: str, request: Request):
        _, take = owned(request, conv_id, share_id)
        share = hub.shares.get(conv_id)
        if not share or share.share_id != share_id or share.status != "active":
            raise HTTPException(409, "screen share is not active")
        try:
            hub.walkthroughs.arm(take, share)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await hub._line_event(conv_id, hub._share_view(share, hub.devices[share.device_id]))
        return {"ok": True}

    @router.post("/api/conversations/{conv_id}/walkthroughs/{share_id}/stop")
    async def stop(conv_id: str, share_id: str, request: Request):
        _, take = owned(request, conv_id, share_id)
        await hub.walkthroughs.stop(take)
        return {"ok": True}

    @router.delete("/api/conversations/{conv_id}/walkthroughs/{share_id}")
    async def cancel(conv_id: str, share_id: str, request: Request):
        _, take = owned(request, conv_id, share_id)
        await hub.walkthroughs.stop(take)
        hub.walkthroughs.discard(share_id)
        return {"ok": True}

    @router.post("/api/conversations/{conv_id}/walkthroughs/{share_id}/finish")
    async def finish(conv_id: str, share_id: str, request: Request, body: Finish):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "write")
        if not is_human(principal):
            raise HTTPException(403, "only a person can send a walkthrough")
        identity = principal_identity(principal)
        key = "walkthrough:" + share_id
        async with claim_key(runtime.db, identity, conv_id, key):
            original = original_for_key(runtime.db, identity, key, conv_id)
            if original:
                return {"message": MessageResponse.model_validate(
                    {**original, "files": store.for_message(original["id"]), "replayed": True})}
            _, take = owned(request, conv_id, share_id)
            deny_unless(runtime.db, principal, conv_id, "upload")
            conv = runtime.db.get_conversation(conv_id)
            if not conv or conv["archived_at"]:
                raise HTTPException(409, "restore the line before sending")
            if not any(a["status"] in ("starting", "running")
                       for a in runtime.db.list_attachments(conv_id)):
                raise HTTPException(409, "attach a process to this line before sending")
            await hub.walkthroughs.stop(take)
            segments = [segment.model_dump() for segment in body.segments]
            frames = select_frames(take.buffer.frames, segments)
            caption = assemble_message(body.notes, segments, frames, body.transcription_error)
            try:
                def prepare():
                    items = []
                    for frame in frames:
                        marked = body.mark_pointer and pointer_coordinates(frame)["frame"] is not None
                        data = _mark_pointer(frame) if marked else frame.data
                        mime = "image/png" if marked else frame.mime
                        items.append(prepared_file((data, "screen-frame", mime)))
                    return items
                prepared = await asyncio.to_thread(prepare)
            except MediaError as exc:
                raise HTTPException(exc.status_code, exc.detail) from exc
            if hub.walkthroughs.items.get(share_id) is not take:
                raise HTTPException(409, "walkthrough was cancelled")
            message = runtime.db.add_message(conv_id, principal.name, "human", "")
            try:
                refs = store.store(conv_id, message["id"], prepared, "Walkthrough frame", None)
            except Exception:
                runtime.db._exec("DELETE FROM messages WHERE id=?", (message["id"],))
                raise
            text = digest_body(caption, refs, "")
            runtime.db._exec("UPDATE messages SET body=? WHERE id=?", (text, message["id"]))
            remember_key(runtime.db, identity, key, conv_id, message["id"])
            stored = {**message, "body": text, "files": refs}
            hub.walkthroughs.discard(share_id)
            await runtime.broadcast(conv_id, MessageEvent(message=MessageResponse.model_validate(stored)))
            await runtime.route_mentions(conv_id, stored)
            return {"message": MessageResponse.model_validate(stored)}

    return router
