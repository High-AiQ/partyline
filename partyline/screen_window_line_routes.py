"""Person-only replacement of a computer's standing line set and picker options."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth_guard import request_principal
from .auth_store import user_by_id
from .hierarchy import descendants
from .machine_scope import allows, is_human
from .screen_audit import reset_window_access_notices
from .screen_device_access import standing_roots
from .screen_window_notices import live_processes


class WindowAccessLines(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conv_ids: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(max_length=1000)


class WindowAccessLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conv_id: str | None = Field(default=None, min_length=1, max_length=128)


class WindowLineOption(BaseModel):
    id: str
    name: str


class WindowLineOptions(BaseModel):
    lines: list[WindowLineOption]


def picker_options(db, principal, selected):
    lines = {line["id"]: line for line in db.list_conversations()}
    for ident in selected:
        if line := db.get_conversation(ident):
            lines[ident] = line
    return [{"id": line["id"], "name": line["name"]} for line in lines.values()
            if allows(db, principal, line["id"], "read") and
            (line["id"] in selected or
             (not line.get("parent_id") and live_processes(db, line["id"])))]


def router_for(runtime, hub):
    router = APIRouter()

    def owner(request, device_id):
        principal = request_principal(request)
        if not is_human(principal) or user_by_id(runtime.db, principal.user_id) is None:
            raise HTTPException(403, "only the paired person can authorize window access lines")
        row = runtime.db._exec("SELECT id FROM screen_devices WHERE id=? AND owner_id=? "
                              "AND revoked_at IS NULL", (device_id, principal.user_id)).fetchone()
        if not row:
            raise HTTPException(404, "computer not found")
        return principal, {"id": device_id, "owner_id": principal.user_id}

    @router.get("/api/screen/devices/{device_id}/window-access-lines", response_model=WindowLineOptions)
    async def options(device_id: str, request: Request):
        principal, device = owner(request, device_id)
        selected = standing_roots(runtime.db, device)
        return {"lines": picker_options(runtime.db, principal, selected)}

    async def replace(device_id, conv_ids, request):
        principal, device = owner(request, device_id)
        selected = set(conv_ids)
        previous = standing_roots(runtime.db, device)
        for ident in selected:
            line = runtime.db.get_conversation(ident)
            if not line or not allows(runtime.db, principal, ident, "read"):
                raise HTTPException(404, "line not found")
            if line.get("archived_at") and ident not in previous:
                raise HTTPException(409, "cannot authorize an archived line")
        removed = previous - selected
        affected = set()
        for ident in removed:
            affected.update({ident, *descendants(runtime.db, ident)})
        # Persist without yielding; a concurrent helper response revalidates this set.
        runtime.db._exec("DELETE FROM screen_device_window_lines WHERE device_id=?", (device_id,))
        for ident in selected:
            runtime.db._exec("INSERT INTO screen_device_window_lines(device_id,conv_id) VALUES(?,?)",
                             (device_id, ident))
        reset_window_access_notices(runtime, device_id)
        await hub.window_grants.revoke_standing(device_id, tell_helper=True, lines=affected)
        from .capability_versions import bump_runtime
        bump_runtime(runtime)
        await hub._device_event(device, device_id in hub.devices)
        return {"ok": True}

    @router.put("/api/screen/devices/{device_id}/window-access-lines")
    async def authorize_lines(device_id: str, body: WindowAccessLines, request: Request):
        return await replace(device_id, body.conv_ids, request)

    @router.put("/api/screen/devices/{device_id}/window-access-line")
    async def authorize_line(device_id: str, body: WindowAccessLine, request: Request):
        # Compatibility: the former single selector replaces the set with zero or one line.
        return await replace(device_id, [body.conv_id] if body.conv_id else [], request)

    return router
