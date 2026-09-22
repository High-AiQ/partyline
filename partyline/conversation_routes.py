"""Conversation CRUD, attach, and archive — scoped for machine credentials."""

from __future__ import annotations

import asyncio
import os
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .adapter_update import apply_update, requested_update_argv
from .attachment_commands import validated_attachment_command
from .auth_guard import request_principal
from .auth_store import handle_taken
from .hierarchy import tree_live_name_conflict
from .line_process_routes import detach_attachment, live_attachments, mid_turn_blocker
from .line_subtree import archive_line, archive_subtree
from .line_worktree import describe, ensure_placed, line_cwd, outside_worktree_note
from .retirement import archive_blockers
from .worktree_lifecycle import archive_worktree_if_safe, discard_worktree
from .review_worktrees import prune_review_worktrees
from .conversation_contracts import BlockedArchiveResponse, PurgeAllResponse
from .conversation_purge import execute_purge, execute_purge_all_archived
from .contracts import (
    ArchiveResponse, AttachIn, AttachmentResponse, ConvIn, ConversationEvent,
    ConversationResponse, ConversationsChangedEvent, PurgeResponse, RenameIn, TopicIn,
)
from .machine_scope import (
    deny_sideways_attach, deny_unless, is_human, visible_conversation_ids,
)
from .message_contracts import ConversationDetailResponse
from .message_routes import conversation_detail_response
from .runtime import NAME_RE, RESERVED_NAMES


def _server():
    from . import server
    return server


def unique_handle(db, conv_id: str, name: str) -> str:
    """The handle itself, or the first ``name-N`` no live process in the tree bears.

    Presets are named by handle, so the same preset used twice in one tree
    collided with a 409 that a captain read as "cannot staff this line".
    """
    candidate, n = name, 1
    while tree_live_name_conflict(db, conv_id, candidate) or handle_taken(db, candidate):
        n += 1
        candidate = f"{name[: 32 - len(str(n)) - 1]}-{n}"
    return candidate


def register_conversation_routes(
    app: FastAPI, runtime, media, presence, adapters, metadata, start
) -> None:
    @app.get("/api/conversations", response_model=list[ConversationResponse])
    async def conversations(request: Request, archived: bool = False):
        db = _server().runtime.db
        rows = db.list_conversations(archived=archived)
        allowed = visible_conversation_ids(db, request_principal(request))
        if allowed is None:
            return rows
        return [row for row in rows if row["id"] in allowed]

    @app.post("/api/conversations", response_model=ConversationResponse)
    async def create_conversation(request: Request, body: ConvIn):
        runtime = _server().runtime
        if not is_human(request_principal(request)):
            raise HTTPException(403, "only a human can open a top-level line")
        name = body.name.strip() or "untitled"
        conv = runtime.db.create_conversation(str(uuid.uuid4()), name)
        await runtime.broadcast_all(ConversationsChangedEvent())
        return conv

    @app.get("/api/conversations/{conv_id}", response_model=ConversationDetailResponse)
    async def conversation_detail(request: Request, conv_id: str):
        s = _server()
        deny_unless(s.runtime.db, request_principal(request), conv_id, "read")
        return await conversation_detail_response(
            s.runtime, s.presence, s.media, conv_id, request_principal(request)
        )

    @app.put("/api/conversations/{conv_id}/topic", response_model=ConversationResponse)
    async def set_topic(request: Request, conv_id: str, body: TopicIn):
        runtime = _server().runtime
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "write")
        conv = db.get_conversation(conv_id)
        topic = body.topic.strip()
        if len(topic) > 3000:
            raise HTTPException(400, "topic is capped at 3000 characters")
        if topic == conv["topic"]:
            return conv
        conv = db.set_topic(conv_id, topic)
        who = f" by @{request_principal(request).name}"
        notice = f"☏ topic set{who}: {topic}" if topic else f"☏ topic cleared{who}"
        await runtime.post_message(conv_id, "system", "system", notice)
        await runtime.broadcast(conv_id, ConversationEvent(conversation=conv))
        await runtime.broadcast_all(ConversationsChangedEvent())
        return conv

    @app.put("/api/conversations/{conv_id}/name", response_model=ConversationResponse)
    async def rename_conversation(request: Request, conv_id: str, body: RenameIn):
        runtime = _server().runtime
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "write")
        conv = db.get_conversation(conv_id)
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "a line needs a name")
        if len(name) > 120:
            raise HTTPException(400, "name is capped at 120 characters")
        if name == conv["name"]:
            return conv
        was = conv["name"]
        conv = db.rename_conversation(conv_id, name)
        who = f" by @{request_principal(request).name}"
        await runtime.post_message(
            conv_id, "system", "system", f"☏ line renamed{who}: {was} → {name}"
        )
        await runtime.broadcast(conv_id, ConversationEvent(conversation=conv))
        await runtime.broadcast_all(ConversationsChangedEvent())
        return conv

    @app.delete("/api/conversations/archived", response_model=PurgeAllResponse)
    async def purge_all_archived(request: Request):
        s = _server()
        if not is_human(request_principal(request)):
            raise HTTPException(403, "only a human can purge all archived lines")
        return await execute_purge_all_archived(s.runtime, s.media, s.runtime.db)

    @app.delete(
        "/api/conversations/{conv_id}",
        response_model=ArchiveResponse,
        responses={409: {"model": BlockedArchiveResponse}},
    )
    async def archive_conversation(
        request: Request, conv_id: str, include_children: bool = False, discard: bool = False,
        stop_processes: bool = False,
    ):
        runtime = _server().runtime
        db = runtime.db
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "archive")
        conv = db.get_conversation(conv_id)
        if conv["archived_at"]:
            raise HTTPException(409, "line is already archived")
        pre_stopped: list[str] = []
        live: list[dict] = []
        if stop_processes:
            live = live_attachments(db, conv_id, include_children)
            working_presence = getattr(runtime, "presence", None) or presence
        # Every blocker in one answer, so a captain fixes them in one pass
        # instead of learning the next one on each round trip.
        blockers = await asyncio.to_thread(
            archive_blockers, db, conv_id,
            include_children=include_children, discard=discard,
            strict=not is_human(principal), ignore_live_processes=stop_processes,
        )
        if stop_processes and (blocker := mid_turn_blocker(live, working_presence)):
            blockers.append(blocker)
        if blockers:
            summary = "; ".join(blocker["message"] for blocker in blockers)
            return JSONResponse(
                status_code=409, content={"detail": summary, "blockers": blockers}
            )
        for attachment in live:
            await detach_attachment(runtime, attachment["id"])
            pre_stopped.append(attachment["name"])
        if include_children:
            stopped, archived = await archive_subtree(runtime, conv_id)
        else:
            stopped, archived = await archive_line(runtime, conv_id), [conv_id]
        stopped = [*pre_stopped, *stopped]
        removed, kept_reason = False, None
        for line_id in archived:
            if discard and line_id == conv_id:
                # The explicit discard: a merged branch's dirty worktree goes.
                line_removed = await asyncio.to_thread(discard_worktree, db, line_id)
                reason = None
            else:
                line_removed, reason = await asyncio.to_thread(
                    archive_worktree_if_safe, db, line_id)
            await asyncio.to_thread(prune_review_worktrees, db, line_id)
            if line_id == conv_id:
                removed, kept_reason = line_removed, reason
        await runtime.broadcast_all(ConversationsChangedEvent())
        return {"ok": True, "archived": True, "stopped": stopped,
                "archived_ids": archived, "worktree_removed": removed,
                "worktree_kept_reason": kept_reason,
                "conversation": db.get_conversation(conv_id)}

    @app.post("/api/conversations/{conv_id}/restore", response_model=ConversationResponse)
    async def restore_conversation(request: Request, conv_id: str):
        runtime = _server().runtime
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "archive")
        conv = db.get_conversation(conv_id)
        if not conv["archived_at"]:
            raise HTTPException(409, "line is not archived")
        conv = db.restore_conversation(conv_id)
        await runtime.post_message(
            conv_id, "system", "system", "☏ line restored from the archive"
        )
        await runtime.broadcast_all(ConversationsChangedEvent())
        return conv

    @app.delete("/api/conversations/{conv_id}/purge", response_model=PurgeResponse)
    async def purge_conversation(request: Request, conv_id: str):
        s = _server()
        runtime = s.runtime
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "archive")
        conv = db.get_conversation(conv_id)
        if not conv["archived_at"]:
            raise HTTPException(409, "archive the line before purging it")
        await execute_purge(runtime, s.media, db, conv)
        await runtime.broadcast_all(ConversationsChangedEvent())
        return {"ok": True, "purged": True}

    @app.post(
        "/api/conversations/{conv_id}/attachments",
        response_model=AttachmentResponse,
    )
    async def attach(request: Request, conv_id: str, body: AttachIn):
        s = _server()
        runtime = s.runtime
        db = runtime.db
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "attach")
        conv = db.get_conversation(conv_id)
        if conv["archived_at"]:
            raise HTTPException(409, "restore the line before attaching to it")
        deny_sideways_attach(db, principal, conv_id)
        if not NAME_RE.match(body.name):
            raise HTTPException(
                400, "name must be alphanumeric ([A-Za-z0-9_.-], max 32)"
            )
        if body.name.lower() in RESERVED_NAMES:
            raise HTTPException(400, f"'{body.name}' is a reserved handle")
        if handle_taken(runtime.db, body.name):
            raise HTTPException(409, f"'{body.name}' is registered to a human account")
        name = unique_handle(db, conv_id, body.name)
        try:
            command = validated_attachment_command(
                body.adapter, body.command, s.ADAPTERS, s.ADAPTER_METADATA
            )
            update_argv = requested_update_argv(
                s.ADAPTER_METADATA, body.adapter, body.update
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        # A machine works where its line works; a person may choose.
        chosen = "" if not is_human(principal) else body.cwd.strip()
        if not chosen and (placed := ensure_placed(db, conv_id)) and describe(placed):
            await runtime.post_message(conv_id, "system", "system", describe(placed))
        cwd = os.path.abspath(os.path.expanduser(
            chosen or line_cwd(db, conv_id) or os.getcwd()))
        if not os.path.isdir(cwd):
            raise HTTPException(400, f"cwd does not exist: {cwd}")
        if warning := outside_worktree_note(db, conv_id, cwd):
            await runtime.post_message(conv_id, "system", "system", warning)
        att_id = str(uuid.uuid4())
        runtime_owner = str(uuid.uuid4())
        att = db.add_attachment(
            att_id,
            conv_id,
            name,
            body.adapter,
            command,
            cwd,
            runtime_owner,
            start_after_history=True,
        )
        if update_argv:
            await apply_update(runtime.post_message, conv_id, name, update_argv)
        return await s._start_attachment(att)

    globals().update({
        "conversations": conversations, "create_conversation": create_conversation,
        "conversation_detail": conversation_detail, "set_topic": set_topic,
        "rename_conversation": rename_conversation, "archive_conversation": archive_conversation,
        "restore_conversation": restore_conversation, "purge_conversation": purge_conversation,
        "purge_all_archived": purge_all_archived, "attach": attach,
    })
