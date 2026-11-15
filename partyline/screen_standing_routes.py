"""MCP endpoints for standing window discovery and no-prompt line attachment."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth_guard import request_principal
from .machine_scope import is_human
from .screen_audit import record_window_access, reset_window_access_notices
from .screen_device_access import standing_devices


class AttachWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window: str = Field(min_length=1, max_length=2048)
    reason: str = Field(min_length=1, max_length=500)


class WindowAccessLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conv_id: str | None = Field(default=None, min_length=1, max_length=128)


def router_for(runtime, hub):
    router = APIRouter()

    @router.put("/api/screen/devices/{device_id}/window-access-line")
    async def authorize_line(device_id: str, body: WindowAccessLine, request: Request):
        principal = request_principal(request)
        if not is_human(principal):
            raise HTTPException(403, "only the paired person can authorize window access lines")
        row = runtime.db._exec("SELECT id FROM screen_devices WHERE id=? AND owner_id=? "
                               "AND revoked_at IS NULL", (device_id, principal.user_id)).fetchone()
        if not row:
            raise HTTPException(404, "computer not found")
        if body.conv_id:
            line = runtime.db.get_conversation(body.conv_id)
            if not line:
                raise HTTPException(404, "line not found")
            if line.get("archived_at"):
                raise HTTPException(409, "cannot authorize an archived line")
        runtime.db._exec("INSERT INTO screen_device_window_access(device_id,enabled,owner_conv_id) "
                        "VALUES(?,0,?) ON CONFLICT(device_id) DO UPDATE "
                        "SET owner_conv_id=excluded.owner_conv_id", (device_id, body.conv_id))
        # Remove outstanding grants before announcing the changed scope.
        reset_window_access_notices(runtime, device_id)
        await hub.window_grants.revoke_standing(device_id, tell_helper=True)
        from .capability_versions import bump_runtime
        bump_runtime(runtime)
        await hub._device_event({"id": device_id, "owner_id": principal.user_id}, device_id in hub.devices)
        return {"ok": True}

    def caller(request, conv_id):
        principal = request_principal(request)
        if is_human(principal) or principal.kind != "machine" or principal.conv_id != conv_id:
            raise HTTPException(403, "standing window access is only available on the caller's own line")
        devices = [device for device in standing_devices(hub, conv_id)
                   if device.get("id") in hub.devices]
        if len(devices) != 1:
            raise HTTPException(403, "no paired person has enabled window access for this line")
        return principal, devices[0]

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
            result = await hub.standing_windows.request(device, "screen_windows", line=conv_id,
                line_id=conv_id, line_name=runtime.db.get_conversation(conv_id)["name"],
                agent=principal.name)
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
            result = await hub.standing_windows.request(device, "attach_window", window=body.window,
                reason=body.reason, line=conv_id, line_id=conv_id,
                line_name=hub.runtime.db.get_conversation(conv_id)["name"], agent=principal.name)
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
