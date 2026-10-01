"""Read and mutate per-line message pins."""

from fastapi import APIRouter, HTTPException, Request

from .auth_guard import request_principal
from .machine_scope import deny_unless, is_human
from .pin_contracts import PinAliasIn, PinCreateIn, PinResponse, PinsChangedEvent
from .pin_store import create_pin, list_pins, remove_pin, set_alias


def pin_router(runtime) -> APIRouter:
    router = APIRouter()

    def readable(request: Request, conv_id: str):
        if runtime.db.get_conversation(conv_id) is None:
            raise HTTPException(404)
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "read")
        return principal

    def writable(principal) -> None:
        if not is_human(principal):
            raise HTTPException(403, "only people can change message pins")

    async def publish(conv_id: str) -> list[dict]:
        pins = list_pins(runtime.db, conv_id)
        await runtime.broadcast(
            conv_id,
            PinsChangedEvent(
                conversation_id=conv_id,
                pins=[PinResponse.model_validate(pin) for pin in pins],
            ),
        )
        return pins

    @router.get("/api/conversations/{conv_id}/pins", response_model=list[PinResponse])
    async def get_pins(request: Request, conv_id: str):
        readable(request, conv_id)
        return list_pins(runtime.db, conv_id)

    @router.post("/api/conversations/{conv_id}/pins", response_model=PinResponse)
    async def post_pin(request: Request, conv_id: str, body: PinCreateIn):
        principal = readable(request, conv_id)
        writable(principal)
        if runtime.db.message_by_id(conv_id, body.message_id) is None:
            raise HTTPException(404, "message not found on this line")
        pin = create_pin(runtime.db, conv_id, body.message_id)
        await publish(conv_id)
        return pin

    @router.put(
        "/api/conversations/{conv_id}/pins/{message_id}", response_model=PinResponse
    )
    async def put_alias(
        request: Request, conv_id: str, message_id: int, body: PinAliasIn
    ):
        principal = readable(request, conv_id)
        writable(principal)
        alias = body.alias.strip() if body.alias else None
        alias = alias or None
        if not set_alias(runtime.db, conv_id, message_id, alias):
            raise HTTPException(404, "pin not found")
        await publish(conv_id)
        return next(pin for pin in list_pins(runtime.db, conv_id) if pin["message_id"] == message_id)

    @router.delete(
        "/api/conversations/{conv_id}/pins/{message_id}", response_model=list[PinResponse]
    )
    async def delete_pin(request: Request, conv_id: str, message_id: int):
        principal = readable(request, conv_id)
        writable(principal)
        if not remove_pin(runtime.db, conv_id, message_id):
            raise HTTPException(404, "pin not found")
        return await publish(conv_id)

    return router
