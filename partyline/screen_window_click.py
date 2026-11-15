"""A click, scroll or drag at a point of a window snapshot, or typing and keys, on a window granted to a line.

A point is in the pixels of an earlier `screen_window_snapshot`. The server converts it with that
snapshot's recorded geometry and refuses anything outside the window's client area; the helper converts it
again with its own copy and refuses a window that moved, resized, closed or was re-granted since. The helper
chooses the route: a Chrome page with a CDP connection gets the input through CDP (no cursor); any other
window needs the person's consent on that computer and uses the real cursor and keyboard, confined to the
window. Typing and keys name no point and need an earlier click in the grant. Every operation goes through
`point_operation`; `screen_window_point` only declares what each one takes.
"""
import json
from typing import ClassVar, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .point_geometry import GeometryError, locate
from .screen_audit import publish, record, record_standing_window_access
from .screen_grants import resolve_window
from .screen_failure_snapshot import attach, failed

POINT_VERSION = 3  # the `windows` hello value that can click at a point
INPUT_VERSION = 4  # ... and scroll, drag, type and press keys
# The helper starts no input later than BUDGET seconds after the request reaches it (a late consent is
# discarded), and one it started finishes within DISPATCH more; the server waits longer than both, so input
# can never go through after the server has reported it unconfirmed.
BUDGET, DISPATCH, MARGIN = 40, 20, 10
WAIT = BUDGET + DISPATCH + MARGIN
STALE = ("that snapshot is unknown or too old for this window: take a fresh screen_window_snapshot "
         "(marks=true for numbered boxes) and use its pixels")
OLD_HELPER = "update the Partyline helper to use screen_window_click"


class PointInput(BaseModel):
    """What every point operation shares; a subclass adds its fields and how they reach the helper."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    window: str | None = Field(default=None, min_length=1, max_length=500)
    capture: Literal["none", "thumb"] = "none"
    operation: ClassVar[str] = "click"

    def pixels(self):
        """The image pixels this operation names, in order; none for the keyboard."""
        return []

    def wire(self, points):
        """The fields the helper gets besides the common ones; `points` are the converted screen pixels."""
        return {}

    def detail(self):
        """What the audit row says about it; never typed text."""
        return {}


class WindowClick(PointInput):
    snapshot: str = Field(min_length=1, max_length=64)
    x: int = Field(ge=0, le=100_000)
    y: int = Field(ge=0, le=100_000)
    button: Literal["left", "right"] = "left"
    clicks: Literal[1, 2] = 1

    def pixels(self):
        return [(self.x, self.y)]

    def wire(self, points):
        return {"snapshot": self.snapshot, "x": self.x, "y": self.y, "screen": list(points[0]),
                "button": self.button, "clicks": self.clicks}

    def detail(self):
        return {"button": self.button, "clicks": self.clicks, "snapshot": self.snapshot,
                "point": [self.x, self.y]}


async def audit(runtime, grant, principal, body, route, result, points=()):
    """Grant, line, process, operation, route, point and result: never pixels, never typed text."""
    info = {"grant": grant["id"], "line": principal.conv_id or grant["conv_id"], "process": principal.name,
            "operation": f"screen_window_{body.operation}", "route": route, **body.detail(),
            "screen": [list(point) for point in points] if len(points) > 1
            else list(points[0] if points else ()),
            "result": result}
    record(runtime.db, grant["id"], principal.conv_id or grant["conv_id"], principal.name,
           json.dumps(info, separators=(",", ":")))
    if message := publish(runtime.db, grant["id"]):
        from .contracts import MessageEvent, MessageResponse
        await runtime.broadcast(grant["conv_id"],
                                MessageEvent(message=MessageResponse.model_validate(message)))


async def point_operation(runtime, hub, store, conv_id, body: PointInput, request: Request,
                          mark=None, generation=None):
    principal = request_principal(request)
    deny_unless(runtime.db, principal, conv_id, "write")
    if body.capture != "none":
        deny_unless(runtime.db, principal, conv_id, "read")
    grant, device = resolve_window(hub, principal, body.window)
    if device.get("windows", 0) < (POINT_VERSION if body.operation == "click" else INPUT_VERSION):
        raise HTTPException(409, OLD_HELPER if body.operation == "click"
                            else "update the Partyline helper to use " + f"screen_window_{body.operation}")
    points = []
    if body.pixels():
        geometry = hub.snapshots.geometry.get(grant["id"], body.snapshot)
        refusal = None if geometry is not None else ("stale", STALE)
        if geometry is not None:
            try:
                points = [locate(geometry, x, y) for x, y in body.pixels()]
            except GeometryError as exc:
                refusal = ("outside", str(exc))
        if refusal:  # nothing was sent: answer like any failure a picture explains, with a fresh marked thumb
            result = {"status": "failed", "reason": refusal[0], "error": refusal[1]}
            await attach(runtime, hub, store, principal, conv_id, grant, result)
            return result
    name = f"point_{body.operation}"
    result = {"status": "unconfirmed"}
    try:
        async with hub.elements.locked(grant["id"]):  # processes on the line never interleave on a window
            if mark is not None:
                look, _, _ = hub.snapshots.looks.target(principal, grant, mark)
                if look["generation"] != generation:
                    raise HTTPException(409, "stale mark; take a fresh screen_window_look")
            await audit(runtime, grant, principal, body, "pending", "requested", points)
            await record_standing_window_access(
                runtime, hub, principal, conv_id, name, body.window, None, "started")
            hub.window_grants.spend(grant)
            kind, extra = ("window_click", {}) if body.operation == "click" else (
                "window_point", {"op": body.operation})
            response = await hub.elements.exchange(
                principal, grant, device, kind, agent=principal.name, **extra, **body.wire(points),
                budget=BUDGET, wait=WAIT, **({"look_generation": generation} if generation else {}))
        result = {key: value for key, value in response.items() if key not in ("type", "request_id")}
    except (TimeoutError, OSError, RuntimeError):
        result = {"status": "unconfirmed", "note": "The helper did not confirm the input; it may have run. "
                  "Do not retry automatically."}
    status = result.get("status", "failed")
    await audit(runtime, grant, principal, body, result.get("route", "none"), status, points)
    await record_standing_window_access(runtime, hub, principal, conv_id, name, body.window, None, status)
    if status in ("completed", "no_effect") and not result.get("grant_ended"):
        hub.elements.action_completed(grant["id"])
        if body.capture == "thumb":  # asked for: the picture after, with no tree read
            await attach(runtime, hub, store, principal, conv_id, grant, result, "after", marks=False)
    if failed(result):  # a failure a picture explains carries one, with marks: a point can be tried at once
        await attach(runtime, hub, store, principal, conv_id, grant, result)
    return result


def click_router(runtime, hub, store):
    from .screen_window_point import POINT_MODELS
    router = APIRouter()

    @router.post("/api/conversations/{conv_id}/screen-control/window-click")
    async def click(conv_id: str, body: WindowClick, request: Request):
        return await point_operation(runtime, hub, store, conv_id, body, request)

    for name, model in POINT_MODELS.items():
        def route(model):
            async def handler(conv_id: str, body: model, request: Request):
                return await point_operation(runtime, hub, store, conv_id, body, request)
            return handler
        router.post(f"/api/conversations/{{conv_id}}/screen-control/window-{name}")(route(model))
    return router
