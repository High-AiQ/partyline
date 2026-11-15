"""Person settings, release publication and audited paused responses for helper updates."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from partyline_helper import __version__
from .auth_guard import request_principal
from .machine_scope import is_human
from .screen_audit import record_window_access
from .op_timing import pushed
from .screen_helper_updates import AutoUpdate, PublishedRelease, HelperUpdating, PAUSED

def router_for(runtime, hub, app):
    router = APIRouter()

    @app.exception_handler(HelperUpdating)
    async def paused(request, exc):
        principal = request_principal(request)
        conv_id = request.path_params.get("conv_id")
        if conv_id:
            kind = request.url.path.rsplit("/", 1)[-1]
            call = {"screen-elements": "uia_read", "element-action": "uia_action",
                    "screen-eval": "uia_action",
                    "screen-window-snapshot": "screenshot", "window-click": "point_click",
                    "screen-windows": "list", "screen-attach-window": "attach"}.get(kind, kind)
            await record_window_access(runtime, conv_id, principal.name, call,
                                       exc.grant.get("process", ""), exc.grant.get("title", ""),
                                       "paused: helper updating")
        return JSONResponse(PAUSED)

    @router.put("/api/screen/devices/{device_id}/auto-update")
    async def setting(device_id: str, body: AutoUpdate, request: Request):
        principal = request_principal(request)
        if not is_human(principal):
            raise HTTPException(403, "only the paired person can enable automatic updates")
        row = runtime.db._exec("SELECT * FROM screen_devices WHERE id=? AND owner_id=? "
                              "AND revoked_at IS NULL", (device_id, principal.user_id)).fetchone()
        if not row:
            raise HTTPException(404, "computer not found")
        previous = runtime.db._exec("SELECT enabled FROM screen_helper_preferences WHERE device_id=?",
                                    (device_id,)).fetchone()
        runtime.db._exec("INSERT INTO screen_helper_preferences VALUES(?,?,1) ON CONFLICT(device_id) "
                        "DO UPDATE SET enabled=excluded.enabled,pending=1", (device_id, int(body.enabled)))
        if bool(previous and previous["enabled"]) != body.enabled:
            hub.updates.audit(device_id, principal.name, f"auto_update={body.enabled}")
        if device := hub.devices.get(device_id):
            await pushed("screen",
                device["socket"].send_json({"type": "set_auto_update", "enabled": body.enabled}))
        await hub._device_event(dict(row), device_id in hub.devices)
        return {"ok": True}

    @router.post("/api/screen/helper-release-published")
    async def published(body: PublishedRelease, request: Request):
        principal = request_principal(request)
        line = runtime.db.get_conversation(principal.conv_id) if principal.conv_id else None
        if not is_human(principal) and not (principal.is_lead and line and not line.get("parent_id")):
            raise HTTPException(403, "release announcements require the root captain or a person")
        if body.version != __version__:
            raise HTTPException(409, "release must match this server's helper version")
        return {"sent": await hub.updates.published()}

    return router
