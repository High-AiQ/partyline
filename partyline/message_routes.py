"""Conversation detail and paginated human-history reads."""

import asyncio

from fastapi import APIRouter, HTTPException, Query

from .attachment_view import attachment_response
from .message_contracts import MessagePageResponse


async def conversation_detail_response(runtime, presence, media, conv_id: str) -> dict:
    conversation = runtime.db.get_conversation(conv_id)
    if conversation is None:
        raise HTTPException(404)
    messages, has_more = runtime.db.message_page(conv_id)
    return {
        "conversation": conversation,
        "messages": media.attach(messages),
        "has_more_messages": has_more,
        "attachments": await asyncio.gather(
            *(attachment_response(att) for att in runtime.db.list_attachments(conv_id))
        ),
        "working": presence.working_ids(conv_id),
        "presence": presence.snapshot(conv_id),
    }


def message_router(runtime, media) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/conversations/{conv_id}/messages",
        response_model=MessagePageResponse,
    )
    async def messages(
        conv_id: str,
        before_id: int | None = Query(default=None, ge=1),
        after_id: int | None = Query(default=None, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        if runtime.db.get_conversation(conv_id) is None:
            raise HTTPException(404)
        try:
            rows, has_more = runtime.db.message_page(
                conv_id, before_id=before_id, after_id=after_id, limit=limit
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"messages": media.attach(rows), "has_more": has_more}

    return router
