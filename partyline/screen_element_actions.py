"""Route element actions to a window granted to the calling process's line, one at a time per window."""
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth_guard import request_principal
from .capability_versions import WINDOW_PRESS_VERSION
from .machine_scope import deny_unless
from .screen_grants import resolve_window
from .screen_tree import OUT_BYTES
from .screen_tree_answer import size
from .screen_timing import timed, phase


ACTIONS = Literal["invoke", "toggle", "set_value", "press", "select", "add_to_selection",
                  "remove_from_selection", "expand", "collapse", "scroll", "set_scroll_percent",
                  "scroll_into_view", "set_range_value", "window_close", "window_minimize", "window_maximize",
                  "window_restore", "window_move", "window_resize"]
# Parameters each action takes; "set_scroll_percent" needs at least one of its two.
PARAMS = {"press": ("key",), "select": ("value",), "set_value": ("value",), "scroll": ("direction", "amount"),
          "set_scroll_percent": ("horizontal_percent", "vertical_percent"),
          "set_range_value": ("number",), "window_move": ("x", "y"), "window_resize": ("width", "height")}
ALL_PARAMS = tuple(name for names in PARAMS.values() for name in names)


class Then(BaseModel):
    """What to read from a fresh snapshot taken right after the action; nothing set means what changed."""
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(default=None, min_length=1, max_length=200)
    value: str | None = Field(default=None, min_length=1, max_length=200)
    control_type: str | None = Field(default=None, min_length=1, max_length=40)
    root: str | None = Field(default=None, min_length=1, max_length=128)
    id: str | None = Field(default=None, min_length=1, max_length=128)
    text: bool = False
    context: int = Field(default=1, ge=0, le=5)
    depth: int = Field(default=1, ge=1, le=3)


class ElementAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    element_id: str = Field(min_length=1, max_length=128)
    action: ACTIONS
    force: bool = False
    window: str | None = Field(default=None, min_length=1, max_length=500)
    value: str | None = Field(default=None, max_length=500)
    key: Literal["enter", "tab", "escape"] | None = None
    direction: Literal["up", "down", "left", "right"] | None = None
    amount: Literal["small", "large"] | None = None
    horizontal_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    vertical_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    number: float | None = Field(default=None, allow_inf_nan=False)
    x: int | None = Field(default=None, ge=-32768, le=32767)
    y: int | None = Field(default=None, ge=-32768, le=32767)
    width: int | None = Field(default=None, ge=1, le=16384)
    height: int | None = Field(default=None, ge=1, le=16384)
    then: Then | None = None

    def parameters(self):
        """Reject missing or foreign parameters, so the helper only sees what the action takes."""
        if self.force and self.action not in ("invoke", "toggle", "select", "expand"):
            raise ValueError("force is supported only for invoke, toggle, select and expand")
        given = {name for name in ALL_PARAMS if getattr(self, name) is not None}
        wanted = set(PARAMS.get(self.action, ()))
        if self.action == "select":
            wanted = given & wanted
        if self.action == "set_scroll_percent":
            if not given & wanted:
                raise ValueError("set_scroll_percent requires horizontal_percent and/or vertical_percent")
            wanted = given & wanted
        if missing := sorted(wanted - given):
            raise ValueError(f"{self.action} requires {', '.join(missing)}")
        if extra := sorted(given - wanted):
            raise ValueError(f"{self.action} does not take {', '.join(extra)}")
        excluded = {"window", "then"} | ({"force"} if not self.force else set())
        return self.model_dump(exclude_none=True, exclude=excluded)


STALE = ("unknown element id: not in the current snapshot (the page changed or it was never read); "
         "find it again, or pass then to see the page after a click")
REFRESH_FAILED = "could not refresh the window; read it again before acting"


async def after(hub, principal, grant, then, result):
    """A new snapshot taken at an event-counter boundary, answered like screen_elements and kept in budget."""
    options = {**then.model_dump(exclude_none=True), "refresh": True, "include_root": True}
    if not any(options.get(key) for key in ("query", "value", "control_type", "root", "id", "text")):
        options["changes"] = True
    try:
        reply = await hub.elements.read(principal, None, grant["id"], options, OUT_BYTES - size(result) - 16)
    except HTTPException as exc:  # the share ended meanwhile: the action still happened
        return {"error": str(exc.detail)}
    return {key: item for key, item in reply.items() if key not in ("window", "snapshot_id")}


@timed
async def element_action(runtime, hub, conv_id: str, body: ElementAction, request: Request):
    principal = request_principal(request)
    deny_unless(runtime.db, principal, conv_id, "write")
    if body.then:
        deny_unless(runtime.db, principal, conv_id, "read")
    try:
        grant, device = resolve_window(hub, principal, body.window)
        message = body.parameters()
        if body.action == "press" and device.get("press", 0) < WINDOW_PRESS_VERSION:
            raise ValueError("update the Partyline helper to use press")
        with phase("target_ms"):
            target, _ = await hub.elements.action_target(principal, grant, body.element_id)
        if target is None:
            return {"status": "failed", "error": REFRESH_FAILED}
        async with hub.elements.locked(grant["id"]):  # processes on the line never interleave on a window
            message["element_id"], known = hub.elements.locked_target(grant["id"], body.element_id)
            if message["element_id"] is None:
                return {"status": "failed", "error": REFRESH_FAILED}
            if not known:
                return {"status": "failed", "error": STALE}
            hub.window_grants.spend(grant)
            response = await hub.elements.exchange(principal, grant, device, "window_element_action",
                                                   agent=principal.name, **message)
        result = {key: value for key, value in response.items() if key not in ("type", "request_id")}
        if result.get("status") in ("completed", "no_effect") and not result.get("grant_ended"):
            if body.then:
                result["after"] = await after(hub, principal, grant, body.then, result)
                if result.get("source") == "cdp" and result.get("settle") == "quiet":
                    observed = result["after"].get("snapshot_event_counter")
                    if (observed != result.get("settled_event_counter")
                            or result["after"].get("change_event_since_snapshot")):
                        result["settle"] = "changing"
            tree = hub.elements.snapshots.get(grant["id"])
            hub.elements.action_completed(grant["id"], bool(body.then and tree))
        return result
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (TimeoutError, OSError, RuntimeError):
        return {"status": "unconfirmed", "note": "The helper did not confirm the action; "
                "it may have run. Do not retry automatically."}
