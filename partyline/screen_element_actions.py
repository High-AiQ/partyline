"""Route element actions to the window granted to the calling attachment."""
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .screen_grants import resolve_window
from .screen_tree import OUT_BYTES
from .screen_tree_answer import size


ACTIONS = Literal["invoke", "toggle", "set_value", "select", "add_to_selection", "remove_from_selection",
                  "expand", "collapse", "scroll", "set_scroll_percent", "scroll_into_view",
                  "set_range_value", "window_close", "window_minimize", "window_maximize",
                  "window_restore", "window_move", "window_resize"]
# Parameters each action takes; "set_scroll_percent" needs at least one of its two.
PARAMS = {"set_value": ("value",), "scroll": ("direction", "amount"),
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
    window: str | None = Field(default=None, min_length=1, max_length=500)
    value: str | None = Field(default=None, max_length=500)
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
        given = {name for name in ALL_PARAMS if getattr(self, name) is not None}
        wanted = set(PARAMS.get(self.action, ()))
        if self.action == "set_scroll_percent":
            if not given & wanted:
                raise ValueError("set_scroll_percent requires horizontal_percent and/or vertical_percent")
            wanted = given & wanted
        if missing := sorted(wanted - given):
            raise ValueError(f"{self.action} requires {', '.join(missing)}")
        if extra := sorted(given - wanted):
            raise ValueError(f"{self.action} does not take {', '.join(extra)}")
        return self.model_dump(exclude_none=True, exclude={"window", "then"})


STALE = ("unknown element id: not in the current snapshot (the page changed or it was never read); "
         "find it again, or pass then to see the page after a click")


async def after(hub, principal, grant, then, result):
    """A new snapshot taken once the page has settled, answered like screen_elements and kept in budget."""
    options = {**then.model_dump(exclude_none=True), "refresh": True}
    if not any(options.get(key) for key in ("query", "value", "control_type", "root", "id", "text")):
        options["changes"] = True
    await hub.elements.settle()
    try:
        reply = await hub.elements.read(principal, None, grant["id"], options, OUT_BYTES - size(result) - 16)
    except HTTPException as exc:  # the share ended meanwhile: the action still happened
        return {"error": str(exc.detail)}
    return {key: item for key, item in reply.items() if key not in ("window", "snapshot_id")}


async def element_action(runtime, hub, conv_id: str, body: ElementAction, request: Request):
    principal = request_principal(request)
    deny_unless(runtime.db, principal, conv_id, "write")
    if body.then:
        deny_unless(runtime.db, principal, conv_id, "read")
    try:
        grant, device = resolve_window(hub, principal, body.window)
        message = body.parameters()
        message["element_id"], known = hub.elements.helper_id(grant["id"], body.element_id)
        if not known:
            return {"status": "failed", "error": STALE}
        hub.window_grants.spend(grant)
        response = await hub.elements.exchange(principal, grant, device, "window_element_action",
                                               agent=principal.name, **message)
        result = {key: value for key, value in response.items() if key not in ("type", "request_id")}
        if body.then and result.get("status") == "completed" and not result.get("grant_ended"):
            result["after"] = await after(hub, principal, grant, body.then, result)
        return result
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (TimeoutError, OSError, RuntimeError):
        return {"status": "unconfirmed", "note": "The helper did not confirm the action; "
                "it may have run. Do not retry automatically."}
