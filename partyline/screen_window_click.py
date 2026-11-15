"""A click at a point of a window snapshot, on a window granted to the caller's line.

The point is in the pixels of an earlier `screen_window_snapshot`. The server converts it with that
snapshot's recorded geometry and refuses anything outside the window's client area; the helper converts it
again with its own copy and refuses a window that moved, resized, closed or was re-granted since. The helper
chooses the route: a Chrome page with a CDP connection is clicked through CDP (no cursor); any other window
needs the person's consent on that computer and uses the real cursor, confined to the window.
"""
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .point_geometry import GeometryError, locate
from .screen_audit import publish, record, record_standing_window_access
from .screen_grants import resolve_window

POINT_VERSION = 3  # the `windows` hello value that can click at a point
# The helper starts no click later than BUDGET seconds after the request reaches it (a late consent is
# discarded), and one it started finishes within DISPATCH more; the server waits longer than both, so a click
# can never go through after the server has reported it unconfirmed.
BUDGET, DISPATCH, MARGIN = 40, 20, 10
WAIT = BUDGET + DISPATCH + MARGIN
STALE = ("that snapshot is unknown or too old for this window: take a fresh screen_window_snapshot "
         "(marks=true for numbered boxes) and click in its pixels")
OLD_HELPER = "update the Partyline helper to use screen_window_click"


class WindowClick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: str = Field(min_length=1, max_length=64)
    x: int = Field(ge=0, le=100_000)
    y: int = Field(ge=0, le=100_000)
    button: Literal["left", "right"] = "left"
    clicks: Literal[1, 2] = 1
    window: str | None = Field(default=None, min_length=1, max_length=500)
    capture: Literal["none", "thumb"] = "none"


async def audit(runtime, grant, principal, body, route, result, point=None):
    """Grant, line, process, operation, route, point and result: never pixels."""
    info = {"grant": grant["id"], "line": principal.conv_id or grant["conv_id"], "process": principal.name,
            "operation": "screen_window_click", "route": route, "button": body.button, "clicks": body.clicks,
            "snapshot": body.snapshot, "point": [body.x, body.y], "screen": list(point or ()),
            "result": result}
    record(runtime.db, grant["id"], principal.conv_id or grant["conv_id"], principal.name,
           json.dumps(info, separators=(",", ":")))
    if message := publish(runtime.db, grant["id"]):
        from .contracts import MessageEvent, MessageResponse
        await runtime.broadcast(grant["conv_id"],
                                MessageEvent(message=MessageResponse.model_validate(message)))


async def window_click(runtime, hub, store, conv_id, body: WindowClick, request: Request):
    principal = request_principal(request)
    deny_unless(runtime.db, principal, conv_id, "write")
    if body.capture != "none":
        deny_unless(runtime.db, principal, conv_id, "read")
    grant, device = resolve_window(hub, principal, body.window)
    if device.get("windows", 0) < POINT_VERSION:
        raise HTTPException(409, OLD_HELPER)
    geometry = hub.snapshots.geometry.get(grant["id"], body.snapshot)
    if geometry is None:
        raise HTTPException(409, STALE)
    try:
        point = locate(geometry, body.x, body.y)
    except GeometryError as exc:
        raise HTTPException(409, str(exc)) from exc
    await audit(runtime, grant, principal, body, "pending", "requested", point)
    await record_standing_window_access(runtime, hub, principal, conv_id, "point_click", body.window, None,
                                        "started")
    result = {"status": "unconfirmed"}
    try:
        async with hub.elements.locked(grant["id"]):  # processes on the line never interleave on a window
            hub.window_grants.spend(grant)
            response = await hub.elements.exchange(
                principal, grant, device, "window_click", agent=principal.name, snapshot=body.snapshot,
                x=body.x, y=body.y, screen=list(point), button=body.button, clicks=body.clicks,
                budget=BUDGET, wait=WAIT)
        result = {key: value for key, value in response.items() if key not in ("type", "request_id")}
    except (TimeoutError, OSError, RuntimeError):
        result = {"status": "unconfirmed", "note": "The helper did not confirm the click; it may have run. "
                  "Do not retry automatically."}
    status = result.get("status", "failed")
    await audit(runtime, grant, principal, body, result.get("route", "none"), status, point)
    await record_standing_window_access(runtime, hub, principal, conv_id, "point_click", body.window, None,
                                        status)
    if status in ("completed", "no_effect") and not result.get("grant_ended"):
        hub.elements.action_completed(grant["id"])
        if body.capture == "thumb":
            result["after"] = await after(hub, principal, store, body.window)
    return result


async def after(hub, principal, store, window):
    """A fresh picture of the window after the click, as the thumb tier only; the click still happened."""
    try:
        picture = await hub.snapshots.take(principal, store, window)
    except HTTPException as exc:
        return {"error": str(exc.detail)}
    thumb = picture["variants"].get("thumb") or picture["variants"].get("slim")
    return {"file": picture["file"], "variants": {"thumb": thumb} if thumb else picture["variants"],
            "snapshot": picture.get("snapshot"), "width": picture["width"], "height": picture["height"]}


def click_router(runtime, hub, store):
    router = APIRouter()

    @router.post("/api/conversations/{conv_id}/screen-control/window-click")
    async def click(conv_id: str, body: WindowClick, request: Request):
        return await window_click(runtime, hub, store, conv_id, body, request)

    return router
