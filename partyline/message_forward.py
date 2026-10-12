"""Forward one line's message to another line, quoted with its origin (5.11).

The manual relay: a captain reads a child line, decides a sibling or the
parent must see one message, and forwards it instead of paraphrasing — the
quote keeps the original author and line, so the receiving room reads the
words as they were said rather than as they were retold. The forwarder is
the sender (its credential, its turn); the quote is the body.

Permission is the pair the action implies: `read` on the source line and
`write` on the target. Nothing else travels — forwarding is speech, not a
capability hand-off.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .message_queries import select_message_by_id
from .message_routing import post_identified


class ForwardIn(BaseModel):
    to: str = Field(min_length=1)
    note: str = Field(default="", max_length=500)


def quote_forward(note: str, line_name: str, author: str, body: str) -> str:
    """The forwarded body: the forwarder's note above the quoted original."""
    head = f"{note.strip()}\n\n" if note.strip() else ""
    return f"{head}↪ forwarded from «{line_name}» — {author} said:\n{body}"


def forward_router(runtime) -> APIRouter:
    router = APIRouter()

    @router.post("/api/conversations/{conv_id}/messages/{message_id}/forward")
    async def forward_message(conv_id: str, message_id: int, body: ForwardIn,
                              request: Request):
        db = runtime.db
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "read")
        deny_unless(db, principal, body.to, "write")
        message = select_message_by_id(db._exec, conv_id, message_id)
        if message is None:
            raise HTTPException(404, "message not found on this line")
        source = db.get_conversation(conv_id) or {}
        quoted = quote_forward(
            body.note, source.get("name") or conv_id,
            message["sender"], message["body"])
        return await post_identified(runtime, body.to, principal, quoted)

    return router
