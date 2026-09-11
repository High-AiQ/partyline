"""Conversation CRUD, attach, and archive — scoped for machine credentials."""

from __future__ import annotations

import os
import uuid

from fastapi import FastAPI, HTTPException, Request

from .adapter_update import apply_update, requested_update_argv
from .attachment_commands import validated_attachment_command
from .auth_guard import request_principal
from .auth_store import handle_taken
from .claim_routes import purge_claims
from .contracts import (
    ArchiveResponse,
    AttachIn,
    AttachmentResponse,
    ConvIn,
    ConversationArchivedEvent,
    ConversationDeletedEvent,
    ConversationEvent,
    ConversationResponse,
    ConversationsChangedEvent,
    PurgeResponse,
    RenameIn,
    TopicIn,
)
from .machine_scope import (
    deny_archive_if_children,
    deny_purge_if_parent_refs,
    deny_unless,
    is_human,
    visible_conversation_ids,
)
from .message_contracts import ConversationDetailResponse
from .message_routes import conversation_detail_response
from .reports import purge_conversation as purge_reports
from .runtime import NAME_RE, RESERVED_NAMES


def _server():
    from . import server
    return server


def register_conversation_routes(
    app: FastAPI, runtime, media, presence, tasks, adapters, metadata, start
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
            s.runtime, s.presence, s.media, conv_id
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

    @app.delete("/api/conversations/{conv_id}", response_model=ArchiveResponse)
    async def archive_conversation(request: Request, conv_id: str):
        runtime = _server().runtime
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "archive")
        conv = db.get_conversation(conv_id)
        if conv["archived_at"]:
            raise HTTPException(409, "line is already archived")
        deny_archive_if_children(db, conv_id)
        event = ConversationArchivedEvent(conversation_id=conv_id)
        await runtime.broadcast(conv_id, event)
        await runtime.broadcast(
            conv_id, ConversationDeletedEvent(conversation_id=conv_id)
        )
        stopped = await runtime.stop_attachments(conv_id)
        conv = db.archive_conversation(conv_id)
        runtime.sockets.pop(conv_id, None)
        await runtime.broadcast_all(ConversationsChangedEvent())
        return {"ok": True, "archived": True, "stopped": stopped, "conversation": conv}

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
        deny_purge_if_parent_refs(db, conv_id)
        await runtime.stop_attachments(conv_id)
        s.media.delete_conversation(conv_id)
        purge_claims(runtime.db, conv_id)
        s.tasks.purge(conv_id)
        purge_reports(db, conv_id)
        db.delete_conversation(conv_id)
        runtime.sockets.pop(conv_id, None)
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
        deny_unless(db, request_principal(request), conv_id, "attach")
        conv = db.get_conversation(conv_id)
        if conv["archived_at"]:
            raise HTTPException(409, "restore the line before attaching to it")
        if not NAME_RE.match(body.name):
            raise HTTPException(
                400, "name must be alphanumeric ([A-Za-z0-9_.-], max 32)"
            )
        if body.name.lower() in RESERVED_NAMES:
            raise HTTPException(400, f"'{body.name}' is a reserved handle")
        if handle_taken(runtime.db, body.name):
            raise HTTPException(409, f"'{body.name}' is registered to a human account")
        for existing in db.list_attachments(conv_id):
            if (
                existing["name"].lower() == body.name.lower()
                and existing["status"] in ("starting", "running")
            ):
                raise HTTPException(409, f"'{body.name}' is already attached")
        try:
            command = validated_attachment_command(
                body.adapter, body.command, s.ADAPTERS, s.ADAPTER_METADATA
            )
            update_argv = requested_update_argv(
                s.ADAPTER_METADATA, body.adapter, body.update
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        cwd = os.path.abspath(os.path.expanduser(body.cwd.strip() or os.getcwd()))
        if not os.path.isdir(cwd):
            raise HTTPException(400, f"cwd does not exist: {cwd}")
        att_id = str(uuid.uuid4())
        runtime_owner = str(uuid.uuid4())
        att = db.add_attachment(
            att_id,
            conv_id,
            body.name,
            body.adapter,
            command,
            cwd,
            runtime_owner,
            start_after_history=True,
        )
        if update_argv:
            await apply_update(runtime.post_message, conv_id, body.name, update_argv)
        return await s._start_attachment(att)

    globals().update(
        {
            "conversations": conversations,
            "create_conversation": create_conversation,
            "conversation_detail": conversation_detail,
            "set_topic": set_topic,
            "rename_conversation": rename_conversation,
            "archive_conversation": archive_conversation,
            "restore_conversation": restore_conversation,
            "purge_conversation": purge_conversation,
            "attach": attach,
        }
    )
