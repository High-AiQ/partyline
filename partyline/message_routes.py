"""Conversation detail, paginated human-history reads, and reliable REST send."""

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request

from .attachment_view import attachment_response
from .auth_guard import request_principal
from .contracts import MessageResponse
from .hierarchy_contracts import MessageIn
from .machine_scope import deny_unless, is_human
from .message_contracts import AroundMessageResponse, MessagePageResponse
from .message_queries import select_message_by_id
from .message_routing import post_identified
from .reaction_store import attach


async def conversation_detail_response(runtime, presence, media, conv_id: str, principal=None) -> dict:
    conversation = runtime.db.get_conversation(conv_id)
    if conversation is None:
        raise HTTPException(404)
    messages, has_more = runtime.db.message_page(conv_id)
    return {
        "conversation": conversation,
        "messages": attach(runtime.db, media.attach(messages), principal),
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
        request: Request,
        conv_id: str,
        before_id: int | None = Query(default=None, ge=1),
        after_id: int | None = Query(default=None, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        if runtime.db.get_conversation(conv_id) is None:
            raise HTTPException(404)
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "read")
        try:
            rows, has_more = runtime.db.message_page(
                conv_id, before_id=before_id, after_id=after_id, limit=limit
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"messages": attach(runtime.db, media.attach(rows), principal), "has_more": has_more}

    @router.get(
        "/api/conversations/{conv_id}/messages/around",
        response_model=AroundMessageResponse,
    )
    async def messages_around(
        request: Request,
        conv_id: str,
        message_id: int = Query(ge=1),
        limit: int = Query(default=10),
    ):
        if runtime.db.get_conversation(conv_id) is None:
            raise HTTPException(404)
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "read")
        limit = max(1, min(limit, 50))
        target = select_message_by_id(runtime.db._exec, conv_id, message_id)
        if target is None:
            raise HTTPException(404, "message not found on this line")
        before, has_before = runtime.db.message_page(
            conv_id, before_id=message_id, limit=limit
        )
        after, has_after = runtime.db.message_page(
            conv_id, after_id=message_id, limit=limit
        )
        rows = [*before, target, *after]
        return {
            "messages": attach(runtime.db, media.attach(rows), principal),
            "has_more_before": has_before,
            "has_more_after": has_after,
        }

    @router.post(
        "/api/conversations/{conv_id}/messages",
        response_model=MessageResponse,
    )
    async def post_message(request: Request, conv_id: str, body: MessageIn):
        principal = request_principal(request)
        capability = (
            "write" if principal.conv_id == conv_id or is_human(principal) else "assign"
        )
        deny_unless(runtime.db, principal, conv_id, capability)
        return await post_identified(runtime, conv_id, principal, body.body)

    return router
