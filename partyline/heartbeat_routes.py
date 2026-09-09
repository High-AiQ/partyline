"""Status, enable, and disable for the root manager's own heartbeat.

Authorization here is narrower than a capability check: enabling names the
caller as owner, so the only machine that may enable is the root lead, acting
on itself. Humans may read and disable — an operator has to be able to switch
off a timer whose owner is wedged — but a human has no attachment to own one.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from . import heartbeat
from .auth_guard import request_principal


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_seconds: float | None = None
    goal: str | None = None


class HeartbeatStatus(BaseModel):
    enabled: bool
    conv_id: str | None
    attachment_id: str | None
    interval_seconds: float
    goal: str | None
    next_due_at: float | None
    seconds_until_due: float | None
    wake_pending: bool
    pending_message_id: int | None


def heartbeat_router(runtime) -> APIRouter:
    router = APIRouter()
    db = runtime.db

    def _caller(request: Request):
        """A human, or the root manager this monitor already belongs to.

        A database can hold more than one root line. Being *a* root manager is
        therefore not standing to touch *this* singleton: once configured, only
        the owning attachment may read, re-point, or switch it off. Humans are
        the deliberate override, because an operator has to be able to reach a
        monitor whose owner is wedged.
        """
        principal = request_principal(request)
        if principal.kind == "user":
            return principal
        if not heartbeat.is_root_lead(db, principal.conv_id, principal.attachment_id):
            raise HTTPException(403, "only the root manager may use the heartbeat")
        row = heartbeat.get(db)
        if row is not None and not heartbeat.owns(
            row, principal.conv_id, principal.attachment_id
        ):
            raise HTTPException(403, "this heartbeat belongs to another line's manager")
        return principal

    @router.get("/api/heartbeat", response_model=HeartbeatStatus)
    def get_heartbeat(request: Request):
        _caller(request)
        return heartbeat.status(db)

    @router.post("/api/heartbeat", response_model=HeartbeatStatus)
    def enable_heartbeat(request: Request, body: HeartbeatIn | None = None):
        principal = _caller(request)
        if principal.kind != "machine":
            # A human has no attachment, so there is no process to remind.
            # Refusing beats silently aiming the timer at someone else.
            raise HTTPException(403, "a person has no process to remind; the root manager enables its own")
        body = body or HeartbeatIn()
        try:
            heartbeat.enable(
                db,
                principal.conv_id,
                principal.attachment_id,
                interval_seconds=body.interval_seconds,
                goal=body.goal,
            )
        except heartbeat.HeartbeatError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        return heartbeat.status(db)

    @router.delete("/api/heartbeat", response_model=HeartbeatStatus)
    def disable_heartbeat(request: Request):
        _caller(request)
        heartbeat.disable(db)
        return heartbeat.status(db)

    return router
