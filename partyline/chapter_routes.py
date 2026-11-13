"""HTTP: preview and start a new chapter of a line (people and that line's captain)."""

from __future__ import annotations

from fastapi import FastAPI, Request

from . import chapters
from .auth_guard import request_principal
from .chapters import ChapterIn, ChapterPreview, ChapterResponse
from .contracts import ConversationResponse, ConversationsChangedEvent
from .machine_scope import deny_unless
from .system_notice import post_system_notice


def register_chapter_routes(app: FastAPI, server) -> None:
    @app.get("/api/conversations/{conv_id}/chapter", response_model=ChapterPreview)
    async def chapter_preview(request: Request, conv_id: str):
        db = server().runtime.db
        deny_unless(db, request_principal(request), conv_id, "read")
        return chapters.preview(db, db.get_conversation(conv_id))

    @app.post("/api/conversations/{conv_id}/chapter", response_model=ChapterResponse)
    async def new_chapter(request: Request, conv_id: str, body: ChapterIn):
        runtime = server().runtime
        db = runtime.db
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "chapter")
        old = db.get_conversation(conv_id)
        new = chapters.create_chapter(db, old, body.name)
        who = f" by @{principal.name}"
        await post_system_notice(runtime, conv_id, f"☏ continued in {chapters.link(new)}{who}",
                                 actor=principal)
        await post_system_notice(runtime, new["id"], f"☏ continues from {chapters.link(old)}{who}",
                                 actor=principal)
        await runtime.broadcast_all(ConversationsChangedEvent())
        return ChapterResponse(conversation=ConversationResponse.model_validate(new),
                               previous=ConversationResponse.model_validate(db.get_conversation(conv_id)),
                               captain_preset=chapters.captain_preset(db, conv_id))
