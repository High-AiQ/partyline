"""MCP endpoints for standing window discovery and no-prompt line attachment."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth_guard import request_principal
from .machine_scope import is_human
from .screen_audit import record_window_access
from .screen_device_access import standing_devices


class AttachWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window: str = Field(min_length=1, max_length=2048)
    reason: str = Field(min_length=1, max_length=500)


def router_for(runtime, hub):
    from .screen_window_line_routes import router_for as line_router
    router = APIRouter()
    router.include_router(line_router(runtime, hub))

    def caller(request, conv_id):
        principal = request_principal(request)
        if is_human(principal) or principal.kind != "machine" or principal.conv_id != conv_id:
            raise HTTPException(403, "standing window access is only available on the caller's own line")
        hub.updates.standing_pause(conv_id)
        devices = [device for device in standing_devices(hub, conv_id)
                   if device.get("id") in hub.devices]
        if len(devices) != 1:
            raise HTTPException(403, "no paired person has enabled window access for this line")
        return principal, devices[0]

    def still_authorized(device, conv_id):
        hub.updates.standing_pause(conv_id)
        if (hub.devices.get(device["id"]) is not device or
                device not in standing_devices(hub, conv_id)):
            raise HTTPException(403, "window access is no longer enabled for this line")

    async def audit(conv_id, principal, call, app="", title="", result="failed", device=None):
        await record_window_access(runtime, conv_id, principal.name, call, app, title, result, device)

    @router.post("/api/conversations/{conv_id}/screen-windows")
    async def screen_windows(conv_id: str, request: Request):
        principal = request_principal(request)
        try:
            principal, device = caller(request, conv_id)
        except HTTPException:
            if not is_human(principal) and principal.conv_id == conv_id:
                await audit(conv_id, principal, "list", "windows", "window list", "denied")
            raise
        await audit(conv_id, principal, "list", "windows", "window list", "started", device)
        try:
            still_authorized(device, conv_id)
            result = await hub.standing_windows.request(device, "screen_windows", line=conv_id,
                line_id=conv_id, line_name=runtime.db.get_conversation(conv_id)["name"],
                agent=principal.name)
            still_authorized(device, conv_id)
        except HTTPException:
            await audit(conv_id, principal, "list", "windows", "window list", "failed", device)
            raise
        if result.get("error"):
            await audit(conv_id, principal, "list", "windows", "window list", "paused", device)
            raise HTTPException(409, result["error"])
        windows = result.get("windows", [])
        await audit(conv_id, principal, "list", "windows", "window list", f"listed {len(windows)}", device)
        return {"windows": [{key: row[key] for key in ("id", "hwnd", "process", "title", "state", "url")
                             if key in row}
                            for row in windows]}

    @router.post("/api/conversations/{conv_id}/screen-attach-window")
    async def screen_attach_window(conv_id: str, body: AttachWindow, request: Request):
        principal = request_principal(request)
        try:
            principal, device = caller(request, conv_id)
        except HTTPException:
            if not is_human(principal) and principal.conv_id == conv_id:
                await audit(conv_id, principal, "attach", "", body.window, "denied")
            raise
        await audit(conv_id, principal, "attach", "", body.window, "started", device)
        try:
            still_authorized(device, conv_id)
            result = await hub.standing_windows.request(device, "attach_window", window=body.window,
                reason=body.reason, line=conv_id, line_id=conv_id,
                line_name=hub.runtime.db.get_conversation(conv_id)["name"], agent=principal.name)
            still_authorized(device, conv_id)
        except HTTPException:
            await audit(conv_id, principal, "attach", "", body.window, "failed", device)
            raise
        if result.get("ok") is not True:
            await audit(conv_id, principal, "attach", "", body.window, "denied", device)
            raise HTTPException(409, result.get("error", "the helper refused the window"))
        entry = hub.runtime.db._exec(
            "SELECT process,title FROM screen_line_window_grants WHERE id=?", (result["window"],)
        ).fetchone()
        await audit(conv_id, principal, "attach", entry["process"] if entry else "",
                    entry["title"] if entry else body.window, "granted", device)
        return {"window": result["window"], "title": result.get("title", "")}

    return router
