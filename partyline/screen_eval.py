"""Agent JavaScript in the active tab of one locally granted Chrome window."""
import json

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .screen_audit import record
from .screen_bounded import bounded
from .screen_grants import resolve_window


class ScreenEval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expression: str = Field(min_length=1, max_length=16000)
    window: str | None = Field(default=None, min_length=1, max_length=500)


def audit_call(hub, principal, grant, operation, length=0):
    info = {"grant": grant["id"], "line": principal.conv_id, "process": principal.name,
            "operation": operation, "input_length": length}
    record(hub.runtime.db, grant["id"], principal.conv_id or grant["conv_id"], principal.name,
           json.dumps(info, separators=(",", ":")))


async def screen_eval(runtime, hub, conv_id, body, request):
    principal = request_principal(request)
    deny_unless(runtime.db, principal, conv_id, "write")
    grant, device = resolve_window(hub, principal, body.window)
    audit_call(hub, principal, grant, "screen_eval", len(body.expression))
    if not device.get("chrome_dom"):
        raise HTTPException(409, "update the helper to use screen_eval")
    async with hub.elements.locked(grant["id"]):
        hub.window_grants.spend(grant)
        try:
            response = await hub.elements.exchange(principal, grant, device, "window_eval",
                expression=body.expression, agent=principal.name)
        except (TimeoutError, OSError, RuntimeError):
            return {"status": "unconfirmed", "note": "JavaScript may have run; do not retry automatically"}
        finally:
            hub.elements.action_completed(grant["id"])
    return bounded({key: value for key, value in response.items() if key not in ("type", "request_id")})
