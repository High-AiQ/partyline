"""Route consented window actions to the computer holding agent control."""
import asyncio
import uuid
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth_guard import request_principal
from .machine_scope import deny_unless


ACTIONS = Literal["invoke", "toggle", "set_value", "select", "add_to_selection", "remove_from_selection",
                  "expand", "collapse", "scroll", "set_scroll_percent", "scroll_into_view",
                  "set_range_value", "window_close", "window_minimize", "window_maximize",
                  "window_restore", "window_move", "window_resize"]
# Parameters each action takes; "set_scroll_percent" needs at least one of its two.
PARAMS = {"set_value": ("value",), "scroll": ("direction", "amount"),
          "set_scroll_percent": ("horizontal_percent", "vertical_percent"),
          "set_range_value": ("number",), "window_move": ("x", "y"), "window_resize": ("width", "height")}
ALL_PARAMS = tuple(name for names in PARAMS.values() for name in names)


class ElementAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    element_id: str = Field(min_length=1, max_length=128)
    action: ACTIONS
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
        return self.model_dump(exclude_none=True)


async def element_action(runtime, hub, conv_id: str, body: ElementAction, request: Request):
    principal = request_principal(request)
    deny_unless(runtime.db, principal, conv_id, "write")
    try:
        share, device = hub.control.target(conv_id)
        grant = hub.control.grants.get(share.share_id)
        if not grant or grant.status != "active":
            raise ValueError("agent control is not granted")
        if grant.holder not in (None, principal.name):
            raise ValueError(f"agent control was granted to {grant.holder}")
        message = body.parameters()
        hub.control._spend(grant)
        ident = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        hub.elements.waiters[ident] = (device["id"], future)
        try:
            async with asyncio.timeout(35):
                await device["socket"].send_json({"type": "window_element_action", "request_id": ident,
                                                 "share_id": share.share_id, "agent": principal.name,
                                                 **message})
                response = await future
            return {key: value for key, value in response.items() if key not in ("type", "request_id")}
        finally:
            hub.elements.waiters.pop(ident, None)
            if not future.done():
                future.cancel()
    except (ValueError, TimeoutError, OSError, RuntimeError) as exc:
        raise HTTPException(409, str(exc) or "helper did not respond") from exc
