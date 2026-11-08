"""Local tools routes: request a session, call a tool op, end it, and the person's revoke."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth_guard import request_principal
from .machine_scope import deny_unless, is_human

MAX_TIMEOUT = 180


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    checker: bool = False
    device: str | None = Field(default=None, max_length=120)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    args: dict = Field(default_factory=dict)
    timeout_s: float = Field(default=20, ge=1, le=MAX_TIMEOUT)


def tools_router(runtime, hub, store) -> APIRouter:
    router = APIRouter()
    base = "/api/conversations/{conv_id}/local-tools"

    @router.get(base)
    async def view(conv_id: str, request: Request):
        deny_unless(runtime.db, request_principal(request), conv_id, "read")
        return {"session": hub.tools.view(conv_id)}

    @router.post(base + "/request")
    async def request_session(conv_id: str, body: ToolRequest, request: Request):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "write")
        conv = runtime.db.get_conversation(conv_id)
        try:
            return await hub.tools.request(conv_id, principal.name, conv["name"], body.tool,
                                           body.checker, body.device)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post(base + "/call")
    async def call(conv_id: str, body: ToolCall, request: Request):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "write")
        try:
            return await hub.tools.call(conv_id, principal.name, body.op, body.args, body.timeout_s, store)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post(base + "/end")
    async def end(conv_id: str, request: Request):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "write")
        try:
            return await hub.tools.end(conv_id, principal.name)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.delete("/api/local-tools/sessions/{session_id}")
    async def revoke(session_id: str, request: Request):
        principal = request_principal(request)
        item = next((s for s in hub.tools.sessions.values() if s.session_id == session_id), None)
        device = hub.devices.get(item.device_id) if item else None
        if not is_human(principal) or not device or device["owner_id"] != principal.user_id:
            raise HTTPException(404, "local tools session not found")
        if not await hub.tools.revoke(item, f"revoked by {principal.name} in Partyline"):
            raise HTTPException(409, "the session is not active")
        return {"ok": True}

    return router
