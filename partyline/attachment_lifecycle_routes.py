"""Explicit fresh-session and stopped-roster HTTP actions."""

import asyncio
import os

from fastapi import HTTPException, Request

from .agent_connection import remove_connection
from .bridge_service import close_for_attachment
from .auth_guard import request_principal
from .machine_scope import deny_unless, deny_unless_attachment, is_human
from .attachment_contracts import AttachmentResponse
from .attachment_lifecycle import (
    FreshAttachmentRequest,
    ReplaceRequest,
    create_fresh_record,
    remove_stopped_record,
    require_stopped,
)
from .contracts import AttachmentEvent, AttachmentRemovedEvent, OkResponse
from .line_process_routes import detach_attachment
from .attachment_tmp import reap_tmp_dir
from .system_notice import post_system_notice
from .mention_relay import post_private


def register_attachment_lifecycle_routes(app, runtime, *, start, require_loopback, validate):
    async def _start_replacement(att, body):
        """Reserve the handle, restore the captain role, and start the fresh session.

        Shared by /fresh and /replace: on a failed start the replacement is
        cleaned up and the failure re-raised, so neither route leaves a
        half-created card behind.
        """
        replacement = await create_fresh_record(runtime.db, att, body)
        if att.get("is_lead"):
            # The fresh record carries the old identity but not its role: a
            # replaced captain is still this line's captain. The old row gives
            # up the one-lead flag first — the index allows exactly one — and
            # the role binds at start, so it must be on the new row before.
            runtime.db._exec("UPDATE attachments SET is_lead=0 WHERE id=?", (att["id"],))
            runtime.db._exec(
                "UPDATE attachments SET is_lead=1 WHERE id=?", (replacement["id"],))
            replacement["is_lead"] = 1
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
            if att.get("is_lead"):
                # The replacement never started: the old row is the captain
                # again, or the line is left with none.
                runtime.db._exec(
                    "UPDATE attachments SET is_lead=1 WHERE id=?", (att["id"],))
            if isinstance(exc, (HTTPException, asyncio.CancelledError)):
                raise
            raise HTTPException(500, f"failed to start fresh: {exc}") from exc
        await remove_stopped_record(runtime.db, att["id"], missing_ok=True)
        await _removed_event(att)
        await runtime.broadcast(att["conv_id"], AttachmentEvent(attachment=response))
        return response

    @app.post("/api/attachments/{att_id}/fresh", response_model=AttachmentResponse)
    async def fresh_attachment(
        request: Request, att_id: str, body: FreshAttachmentRequest | None = None
    ):
        require_loopback(request)
        deny_unless_attachment(runtime.db, request_principal(request), att_id, "attach")
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
        return await _start_replacement(att, body)

    @app.post("/api/attachments/{att_id}/replace", response_model=AttachmentResponse)
    async def replace_attachment(att_id: str, body: ReplaceRequest, request: Request):
        """Finding 2.8: a thrashing or stuck process becomes a fresh instance of itself.

        The line's captain — or a person — stops the old process and starts a
        new one with the same handle, preset, command and working directory
        and a **new CLI session**: clean context is the point. The captain
        role survives, and the re-briefing (the line's notes and the latest
        assignment) rides the first briefing as the checkpoint, so the fresh
        process picks the work back up instead of guessing.
        """
        db = runtime.db
        principal = request_principal(request)
        att = db.get_attachment(att_id)
        if att is None:
            raise HTTPException(404, "attachment not found")
        if not is_human(principal):
            deny_unless(db, principal, att["conv_id"], "assign")
        if att_id in runtime.live:
            await detach_attachment(runtime, att_id, survivors=False)
        stopped = require_stopped(db, att_id)
        try:
            validate(stopped)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not os.path.isdir(stopped["cwd"]):
            raise HTTPException(400, "attachment working directory no longer exists")
        from .mention_relay import live_manager
        from .rebrief import render_rebrief

        response = await _start_replacement(
            stopped, FreshAttachmentRequest(checkpoint=render_rebrief(
                db, stopped, reason=body.reason.strip())))
        replacement_id = response["id"]
        # Finding 5.7: the fresh instance says hello without an @, so ring the
        # line's live captain once with the assignment ask. Skipped when the
        # replaced process was itself the captain — its fresh instance already
        # holds the role and needs no ring.
        if not stopped.get("is_lead"):
            captain = live_manager(runtime, stopped["conv_id"])
            if captain is not None:
                await post_private(
                    runtime, stopped["conv_id"], "system", "system",
                    f"↻ @{stopped['name']} was replaced with a fresh instance "
                    f"(by @{principal.name}) — assign now: "
                    f"@{response['name']} is ready and waiting for your @mention",
                    audience=captain["id"],
                    source=(replacement_id, stopped["conv_id"]),
                )
        await post_system_notice(
            runtime, stopped["conv_id"],
            f"↻ @{stopped['name']} replaced with a fresh instance "
            f"(by @{principal.name}): {body.reason.strip()}",
            actor=principal,
        )
        return response


    async def _removed_event(att):
        await close_for_attachment(runtime, att["id"], "ambassador removed")
        remove_connection(runtime.db.path, att["id"])
        runtime.uncredited.pop(att["id"], None)
        runtime.unclaimed_noticed.discard(att["id"])
        runtime.reattaching.discard(att["id"])
        await runtime.broadcast(att["conv_id"], AttachmentRemovedEvent(
            attachment_id=att["id"], conversation_id=att["conv_id"],
        ))


    @app.delete("/api/attachments/{att_id}/record", response_model=OkResponse)
    async def remove_attachment_record(request: Request, att_id: str):
        # Deliberately not loopback. `require_loopback` exists so that starting
        # and stopping a pty stays with the host that owns it; removing a
        # stopped card controls no process — it deletes a row whose process is
        # already gone. Requiring host locality here refused an operator's own
        # LAN browser with a process-control message about something that
        # controls nothing, and left a detached record unremovable from the
        # only interface that shows it.
        #
        # What actually protects this route is unchanged: the `close`
        # capability below, and two live-process refusals — the tracked-process
        # check here, and `remove_stopped_record`, which re-reads the status
        # under the lock, so a process that starts between them is still
        # refused.
        deny_unless_attachment(runtime.db, request_principal(request), att_id, "close")
        if att_id in runtime.live:
            raise HTTPException(409, "detach the process before removing it")
        att = await remove_stopped_record(runtime.db, att_id)
        reap_tmp_dir(att_id)
        await _removed_event(att)
        return {"ok": True}


