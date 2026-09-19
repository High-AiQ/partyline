"""HTTP endpoints for message reactions."""

from fastapi import APIRouter, HTTPException, Request

from .auth_guard import Principal, request_principal
from .contracts import MessageResponse
from .machine_scope import is_human
from .mention_relay import post_private
from .reaction_contracts import ReactionEvent, ReactionRequest
from .reaction_store import (
    message,
    remove,
    toggle,
    valid_emoji,
    with_reactions,
)


def _reactor_type(principal: Principal) -> str:
    return "agent" if principal.kind == "machine" else "human"


def _authorize(db, principal: Principal, conv_id: str) -> None:
    if not is_human(principal) and principal.conv_id != conv_id:
        raise HTTPException(403, "this credential cannot react on that line")


def _snippet(body: str) -> str:
    compact = " ".join(body.split())
    return compact[:80] + ("…" if len(compact) > 80 else "")


def _target(db, item: dict) -> dict | None:
    target_id = item.get("audience_attachment_id") or item.get("source_attachment_id")
    if target_id:
        return db.get_attachment(target_id)
    wanted = item["sender"].lower()
    return next(
        (
            attachment for attachment in db.list_attachments(item["conv_id"])
            if attachment["name"].lower() == wanted
        ),
        None,
    )


async def _wake_process(runtime, item: dict, principal: Principal, emoji: str) -> None:
    """Tell the machine whose message was reacted to, and wake it now.

    A human's reaction may be their entire answer — approval, intent — so it
    is delivered as a private copy addressed to that process alone, the way
    return-path notices are: shown to the humans and stamped on the message,
    but never a public line addressed to the room, and never sent for a
    reaction on a human's message, which is conversation between people.
    """
    if principal.kind != "user" or item["sender_type"] != "agent":
        return
    target = _target(runtime.db, item)
    if target is None or target["status"] != "running":
        return
    adapter = runtime.live.get(target["id"])
    if adapter is None or not runtime.activation_matches(adapter, target):
        return
    body = f"☺ {principal.name} reacted {emoji} to your «{_snippet(item['body'])}»"
    await post_private(
        runtime,
        target["conv_id"],
        "system",
        "system",
        body,
        audience=target["id"],
        route=True,
    )


def reaction_router(runtime) -> APIRouter:
    router = APIRouter()

    async def mutate(request: Request, message_id: int, emoji: str, *, add: bool):
        principal = request_principal(request)
        item = message(runtime.db, message_id)
        if item is None:
            raise HTTPException(404, "message not found")
        _authorize(runtime.db, principal, item["conv_id"])
        if not valid_emoji(emoji):
            raise HTTPException(400, "unknown reaction emoji")
        if add:
            toggle(runtime.db, message_id, principal.name, _reactor_type(principal), emoji)
        else:
            remove(runtime.db, message_id, principal.name, emoji)
        updated = with_reactions(runtime.db, item, principal)
        await runtime.broadcast(
            item["conv_id"],
            ReactionEvent(message_id=message_id, reactions=updated["reactions"]),
        )
        if any(
            reaction["emoji"] == emoji and reaction["mine"]
            for reaction in updated["reactions"]
        ):
            await _wake_process(runtime, item, principal, emoji)
        return updated

    @router.post("/api/messages/{message_id}/reactions", response_model=MessageResponse)
    async def post_reaction(request: Request, message_id: int, body: ReactionRequest):
        return await mutate(request, message_id, body.emoji, add=True)

    @router.delete("/api/messages/{message_id}/reactions/{emoji}", response_model=MessageResponse)
    async def delete_reaction(request: Request, message_id: int, emoji: str):
        return await mutate(request, message_id, emoji, add=False)

    return router
