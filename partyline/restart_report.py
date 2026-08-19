"""Where a failed restart trigger reports, without impersonating anyone.

The restart watchdog runs outside every attachment and user session — it is
spawned by systemd with the *server's* environment, which never contains a
PARTYLINE_TOKEN. Pretending it is a chat participant would be a fake
identity, so instead the plan it serves carries its own capability: a
``report_token`` minted with the plan and shared only with the trigger. The
route is additionally loopback-guarded (the trigger is always local), but
loopback is belt-and-braces — the token alone is the credential, because an
address is not an identity.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .contracts import OkResponse


class FailureReportIn(BaseModel):
    token: str
    message: str = Field(max_length=2000)


def restart_report_router(runtime, require_loopback) -> APIRouter:
    router = APIRouter()

    @router.post("/api/restart-plan/failure", response_model=OkResponse)
    async def report_restart_failure(request: Request, body: FailureReportIn):
        require_loopback(request)
        plan = runtime.db.get_restart_plan()
        expected = (plan or {}).get("report_token") or ""
        # A mismatch is 404, like the hooks route: a caller probing tokens is
        # not told whether a plan exists at all.
        if not expected or not secrets.compare_digest(body.token, expected):
            raise HTTPException(404)
        message = body.message.strip()
        if message:
            await runtime.post_message(
                plan["conversation_id"], "system", "system", f"⚠ {message}"
            )
        return {"ok": True}

    return router
