"""A captain asks for a service restart; a person approves it with one click.

The agents can carry a change all the way — implement, review, merge, pull —
and then hit a wall: a machine credential may not plan a restart of the
whole service, because a restart bounces every process in every room. That
refusal is right, and it left the last step manual for the person. This is
the hand-off: the captain files a request with a reason, every open tab
shows it, and a person approves it in a confirmation dialog. Approval
persists an automatic reattach plan for every live process (the same plan
the cockpit's arm procedure uses), warns every tab, and restarts the unit;
the new process resumes everyone and rings whoever was mid-turn.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .auth_guard import request_principal
from .contracts import RestartPlanRequest, RestartRequestEvent, ShutdownEvent
from .machine_scope import deny_unless, is_human
from .reattach import RestartPlanError, create_restart_plan

logger = logging.getLogger(__name__)
RESTART_DELAY_SECONDS = 2


class RestartRequestIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class RestartRequest(BaseModel):
    id: str
    conversation_id: str
    requester: str
    reason: str
    created_at: float


class PendingRestart(BaseModel):
    request: RestartRequest | None = None


def service_unit() -> str | None:
    """The systemd user unit this process runs under, from its own cgroup."""
    try:
        with open("/proc/self/cgroup", encoding="utf-8") as fh:
            found = re.search(r"/(partyline[^/\s]*\.service)", fh.read())
    except OSError:
        return None
    return found.group(1) if found else None


def schedule_unit_restart(unit: str, delay: int = RESTART_DELAY_SECONDS) -> bool:
    """Ask systemd to restart the unit shortly, from outside this process.

    Exiting on our own would not bring the service back: the unit restarts
    only on failure. A transient timer runs the restart after the approval
    response has been flushed and the tabs have been told.
    """
    command = [
        "systemd-run", "--user", f"--unit=partyline-approved-restart-{uuid.uuid4().hex[:8]}",
        f"--on-active={delay}s", "systemctl", "--user", "restart", unit,
    ]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        logger.exception("could not schedule the approved restart")
        return False
    if done.returncode:
        logger.error("systemd refused the approved restart: %s", done.stderr.strip())
    return done.returncode == 0


def register_restart_request_routes(app: FastAPI, runtime, adapter_metadata, request_exit) -> None:
    runtime.restart_request = None

    async def announce(conv_id: str, text: str) -> None:
        await runtime.post_message(conv_id, "system", "system", text)
        await runtime.broadcast_all(RestartRequestEvent(request=runtime.restart_request))

    @app.get("/api/restart-request", response_model=PendingRestart)
    async def pending(request: Request):
        request_principal(request)
        return PendingRestart(request=runtime.restart_request)

    @app.post("/api/conversations/{conv_id}/restart-request", response_model=RestartRequest)
    async def file_request(request: Request, conv_id: str, body: RestartRequestIn):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "assign")  # the line's captain, or a person
        if runtime.restart_request is not None:
            raise HTTPException(409, "a restart request is already waiting for a person")
        runtime.restart_request = RestartRequest(
            id=uuid.uuid4().hex[:12], conversation_id=conv_id, requester=principal.name,
            reason=body.reason.strip(), created_at=time.time(),
        )
        await announce(conv_id, f"☏ @{principal.name} asks a person to restart partyline: "
                                f"{runtime.restart_request.reason} — approve or decline from the banner")
        return runtime.restart_request

    def _take(request: Request, request_id: str) -> RestartRequest:
        if not is_human(request_principal(request)):
            raise HTTPException(403, "only a person may decide a restart")
        current = runtime.restart_request
        if current is None or current.id != request_id:
            raise HTTPException(404, "that restart request is no longer pending")
        return current

    @app.post("/api/restart-request/{request_id}/approve", response_model=PendingRestart)
    async def approve(request: Request, request_id: str):
        current = _take(request, request_id)
        who = request_principal(request).name
        unit = service_unit()
        if unit is None and request_exit is None:
            raise HTTPException(409, "partyline is not running under systemd; restart it by hand")
        try:
            create_restart_plan(runtime, adapter_metadata, RestartPlanRequest(
                conversation_id=current.conversation_id, debrief=current.reason,
                mode="automatic", scope="all",
            ))
        except RestartPlanError as exc:
            if exc.status_code != 409:  # 409 = nothing live to resume: still restart
                raise HTTPException(exc.status_code, exc.detail) from exc
        runtime.restart_request = None
        await announce(current.conversation_id,
                       f"☏ restart approved by @{who} — partyline is restarting; every live "
                       "process is resumed with its context when it is back")
        for conv_id in list(runtime.sockets):
            await runtime.broadcast(conv_id, ShutdownEvent())
        if unit is not None:
            if not schedule_unit_restart(unit):
                raise HTTPException(500, "systemd refused to schedule the restart")
        else:
            asyncio.get_running_loop().call_later(RESTART_DELAY_SECONDS, request_exit)
        return PendingRestart(request=None)

    @app.delete("/api/restart-request/{request_id}", response_model=PendingRestart)
    async def decline(request: Request, request_id: str):
        current = _take(request, request_id)
        runtime.restart_request = None
        await announce(current.conversation_id,
                       f"☏ restart declined by @{request_principal(request).name}")
        return PendingRestart(request=None)
