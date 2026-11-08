"""Route consented window actions to the computer holding agent control."""
import asyncio
import uuid
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth_guard import request_principal
from .machine_scope import deny_unless


class ElementAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    element_id: str = Field(min_length=1, max_length=128)
    action: Literal["invoke", "toggle", "set_value"]
    value: str | None = Field(default=None, max_length=500)


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
        if body.action == "set_value" and body.value is None:
            raise ValueError("set_value requires a value")
        hub.control._spend(grant)
        ident = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        hub.elements.waiters[ident] = (device["id"], future)
        try:
            async with asyncio.timeout(35):
                await device["socket"].send_json({"type": "window_element_action", "request_id": ident,
                                                 "share_id": share.share_id, "agent": principal.name,
                                                 **body.model_dump()})
                response = await future
            return {key: value for key, value in response.items() if key not in ("type", "request_id")}
        finally:
            hub.elements.waiters.pop(ident, None)
            if not future.done():
                future.cancel()
    except (ValueError, TimeoutError, OSError, RuntimeError) as exc:
        raise HTTPException(409, str(exc) or "helper did not respond") from exc
