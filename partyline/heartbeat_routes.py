"""Status, enable, and disable for the root manager's own heartbeat.

Authorization here is narrower than a capability check: enabling names the
caller as owner, so the only machine that may enable is the root lead, acting
on itself. Humans may read and disable — an operator has to be able to switch
off a timer whose owner is wedged — but a human has no attachment to own one.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from . import heartbeat, heartbeat_files, heartbeat_snapshot
from .auth_guard import request_principal


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_seconds: float | None = None
    goal: str | None = None
    quiet_if_unchanged: bool = True


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
    since_id: int
    snapshot_hash: str | None
    quiet_wakes: int
    quiet_if_unchanged: bool


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
                quiet_if_unchanged=body.quiet_if_unchanged,
            )
        except heartbeat.HeartbeatError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        return heartbeat.status(db)

    @router.get("/api/heartbeat/status")
    def get_heartbeat_snapshot(request: Request):
        """The same delta a wake would carry, without spending a turn on it.

        Readable at any time, and identical to what the reminder inlines, so
        an operator can see exactly what the monitor is or is not reacting to.
        """
        _caller(request)
        row = heartbeat.get(db)
        if row is None:
            raise HTTPException(404, "no heartbeat is configured")
        snapshot = heartbeat_snapshot.build(
            db, row["conv_id"], row["since_id"], row["attachment_id"]
        )
        return {
            "snapshot": snapshot,
            "hash": heartbeat_snapshot.canonical_hash(snapshot),
            "actionable": heartbeat_snapshot.is_actionable(snapshot),
            "stalled": heartbeat_snapshot.stalled_lines(snapshot),
            "quiet_wakes": row["quiet_wakes"],
        }

    @router.get("/api/heartbeat/snapshots/{digest}")
    def get_saved_snapshot(request: Request, digest: str):
        """Fetch a snapshot a reminder pointed at.

        The digest is validated against a strict pattern before it becomes a
        filename, so nothing a caller sends can leave the snapshot directory.
        An unknown or malformed digest is the same answer: 404.
        """
        _caller(request)
        saved = heartbeat_files.read(runtime.db.path, digest)
        if saved is None:
            raise HTTPException(404, "no snapshot with that digest")
        return saved

    @router.delete("/api/heartbeat", response_model=HeartbeatStatus)
    def disable_heartbeat(request: Request):
        _caller(request)
        heartbeat.disable(db)
        return heartbeat.status(db)

    return router
