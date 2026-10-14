"""Line-bridge API: a person opens and closes; anyone on a line may read its bridge."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import bridge_store as store
from .auth_guard import request_principal
from .bridge_service import close_bridge, open_bridge
from .contracts import MessageResponse
from .machine_scope import deny_unless, is_human


class BridgeEnd(BaseModel):
    conv_id: str
    attachment_id: str


class BridgeIn(BaseModel):
    a: BridgeEnd
    b: BridgeEnd


def bridge_router(runtime) -> APIRouter:
    router = APIRouter()

    def person(request: Request):
        principal = request_principal(request)
        if not is_human(principal):
            raise HTTPException(403, "only people can open, close or read bridges")
        return principal

    def known(bridge_id: str) -> dict:
        bridge = store.get_bridge(runtime.db, bridge_id)
        if bridge is None:
            raise HTTPException(404, "no such bridge")
        return bridge

    @router.post("/api/bridges")
    async def post_bridge(request: Request, body: BridgeIn):
        principal = person(request)
        return await open_bridge(
            runtime, body.a.model_dump(), body.b.model_dump(), principal.name)

    @router.get("/api/bridges")
    async def get_bridge(request: Request, conv_id: str):
        if runtime.db.get_conversation(conv_id) is None:
            raise HTTPException(404)
        deny_unless(runtime.db, request_principal(request), conv_id, "read")
        bridge = store.open_bridge_for_line(runtime.db, conv_id)
        return store.view(runtime.db, bridge) if bridge else None

    @router.delete("/api/bridges/{bridge_id}")
    async def delete_bridge(request: Request, bridge_id: str):
        principal = person(request)
        bridge = known(bridge_id)
        await close_bridge(runtime, bridge, principal.name, f"closed by {principal.name}")
        return store.view(runtime.db, known(bridge_id))

    @router.get("/api/bridges/{bridge_id}/messages")
    async def bridge_messages(request: Request, bridge_id: str):
        person(request)
        known(bridge_id)
        return [MessageResponse.model_validate(row)
                for row in store.audit_log(runtime.db, bridge_id)]

    return router
