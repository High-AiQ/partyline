"""The decision side of write-set requests: approve, deny with a reason, withdraw.

Split from `write_set_requests.py` (filing and helpers live there) for the
line budget. Deciding is a person's act — or, since 5.9, an ancestor
captain deciding strictly inside a write grant or writable checkout its own
line already holds.
"""

from __future__ import annotations

import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import docker_relay, docker_workloads, fence_paths, fence_workspaces
from .auth_guard import request_principal
from .machine_scope import deny_unless, is_human
from .mention_relay import post_private
from .system_notice import post_system_notice
from .hierarchy import ancestors, lead_attachment
from .write_set_requests import (
    PendingWriteSetGrant,
    WriteSetGrantRequest,
    non_resumable_live_attachments,
    pending_model,
    resume_granted_scope,
    resume_line_attachments,
)
from .contracts import WriteSetGrantRequestEvent
from .write_set_routes import add_write_grant


class ApproveIn(BaseModel):
    docker_mode: Literal["managed", "unrestricted"] = "managed"


class WriteSetDenyIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def _machine_decision_error(db, principal, conv_id: str,
                            request: WriteSetGrantRequest) -> str | None:
    """403 text when an ancestor captain may not decide this request (5.9).

    The captain must be the live lead of a strict ancestor of the line, must
    not be the requester, and the requested path must resolve inside a write
    grant the captain's own line holds or a writable entry of its own fence
    write set (checkout, Git carve-outs, `.review/`, `.scratch/`). Anything
    wider is a person's call.
    """
    if docker_relay.is_docker_socket(request.path):
        return "docker access is root-equivalent; a person decides"
    if not principal.is_lead:
        return "outside your grants; a person decides"
    if principal.conv_id not in ancestors(db, conv_id):
        return "outside your grants; a person decides"
    lead = lead_attachment(db, principal.conv_id)
    if (lead is None or lead["id"] != principal.attachment_id
            or lead["status"] not in ("starting", "running")):
        return "outside your grants; a person decides"
    if (request.requester_attachment_id
            and request.requester_attachment_id == principal.attachment_id):
        return "outside your grants; a person decides"
    wanted = os.path.realpath(request.path)
    rows = db._exec(
        "SELECT path FROM conversation_write_grants WHERE conv_id=?",
        (principal.conv_id,)).fetchall()
    for row in rows:
        base = os.path.realpath(row["path"])
        if wanted == base or wanted.startswith(base + "/"):
            return None
    fence_workspaces.load(db, lead)
    for src, _dst, read_only in fence_paths.write_set(lead, create=False):
        base = os.path.realpath(src)
        if not read_only and (wanted == base or wanted.startswith(base + "/")):
            return None
    return "outside your grants; a person decides"


def make_announcer(runtime):
    async def announce(conv_id: str, text: str, *, actor=None) -> None:
        await post_system_notice(runtime, conv_id, text, actor=actor)
        await runtime.broadcast(
            conv_id, WriteSetGrantRequestEvent(request=pending_model(runtime.db, conv_id).request))
    return announce


def register_write_set_request_routes(app: FastAPI, runtime, resume) -> None:
    announce = make_announcer(runtime)

    async def ring_requester(request: WriteSetGrantRequest, text: str, *, actor) -> None:
        if not request.requester_attachment_id:
            return
        target = runtime.db.get_attachment(request.requester_attachment_id)
        if target is None:
            return
        await post_private(
            runtime, target["conv_id"], "system", "system", text,
            audience=target["id"], actor=actor,
        )

    @app.get("/api/conversations/{conv_id}/write-set/request",
             response_model=PendingWriteSetGrant)
    async def pending(request: Request, conv_id: str):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "read")
        return pending_model(runtime.db, conv_id)

    def _pending_request(conv_id: str, request_id: str) -> WriteSetGrantRequest:
        current = pending_model(runtime.db, conv_id).request
        if current is None or current.id != request_id:
            raise HTTPException(404, "that write-set request is no longer pending")
        return current

    def _take_for_decision(request: Request, conv_id: str, request_id: str):
        """A person, or an ancestor captain deciding inside its own grants (5.9)."""
        principal = request_principal(request)
        current = _pending_request(conv_id, request_id)
        if not is_human(principal):
            error = _machine_decision_error(runtime.db, principal, conv_id, current)
            if error:
                raise HTTPException(403, error)
        return current, principal

    def _take_person_only(request: Request, conv_id: str, request_id: str):
        principal = request_principal(request)
        if not is_human(principal):
            raise HTTPException(403, "only a person may decide a write-set request")
        return _pending_request(conv_id, request_id)

    @app.post("/api/conversations/{conv_id}/write-set/request/{request_id}/approve",
              response_model=PendingWriteSetGrant)
    async def approve(request: Request, conv_id: str, request_id: str, body: ApproveIn | None = None):
        current, principal = _take_for_decision(request, conv_id, request_id)
        mode = body.docker_mode if body else "managed"
        blocked = non_resumable_live_attachments(runtime, conv_id, current.path)
        if blocked:
            names = ", ".join(f"@{att['name']} ({att['adapter']})" for att in blocked)
            raise HTTPException(
                409,
                f"cannot approve while live processes cannot resume: {names}; "
                "detach them first",
            )
        who = principal.name
        add_write_grant(runtime.db, conv_id, current.path, who, mode)
        with runtime.db.lock:
            runtime.db.conn.execute(
                "DELETE FROM conversation_write_grant_requests WHERE conv_id=? AND id=?",
                (conv_id, request_id))
            runtime.db.conn.commit()
        _resumed, failed = await resume_granted_scope(
            runtime, conv_id, current.path, resume, resume_line_attachments)
        text = (f"☏ write-set grant for `{current.path}` approved by @{who} — "
                "live processes on this line are resumed with the widened bind")
        if docker_relay.is_docker_socket(current.path):
            text = (f"☏ {docker_workloads.mode_text(mode)} granted by @{who} — every live process "
                    "is resumed so other lines cannot reach the relay")
        if failed:
            text += (f" — could not resume @{', @'.join(failed)}; "
                     "re-attach them by hand")
        await announce(conv_id, text)
        await ring_requester(current, text, actor=principal)
        return PendingWriteSetGrant(request=None)

    @app.delete("/api/conversations/{conv_id}/write-set/request/{request_id}",
                 response_model=PendingWriteSetGrant)
    async def decline(request: Request, conv_id: str, request_id: str):
        current = _take_person_only(request, conv_id, request_id)
        principal = request_principal(request)
        with runtime.db.lock:
            runtime.db.conn.execute(
                "DELETE FROM conversation_write_grant_requests WHERE conv_id=? AND id=?",
                (conv_id, request_id))
            runtime.db.conn.commit()
        text = f"☏ write-set request for `{current.path}` declined by @{principal.name}"
        await announce(conv_id, text)
        await ring_requester(current, text, actor=principal)
        return PendingWriteSetGrant(request=None)

    @app.post("/api/conversations/{conv_id}/write-set/request/{request_id}/deny")
    async def deny(request: Request, conv_id: str, request_id: str,
                   body: WriteSetDenyIn):
        current, principal = _take_for_decision(request, conv_id, request_id)
        with runtime.db.lock:
            runtime.db.conn.execute(
                "DELETE FROM conversation_write_grant_requests WHERE conv_id=? AND id=?",
                (conv_id, request_id))
            runtime.db.conn.commit()
        text = (f"☏ write-set request for `{current.path}` declined by "
                f"@{principal.name}: {body.reason}")
        await announce(conv_id, text)
        await ring_requester(current, text, actor=principal)
        return {"ok": True}

    @app.post("/api/conversations/{conv_id}/write-set/request/{request_id}/withdraw")
    async def withdraw(request: Request, conv_id: str, request_id: str):
        # 5.8: only the process that filed the request may take it back.
        principal = request_principal(request)
        current = pending_model(runtime.db, conv_id).request
        if current is None or current.id != request_id:
            raise HTTPException(404, "that write-set request is no longer pending")
        if (not principal.attachment_id
                or principal.attachment_id != current.requester_attachment_id):
            raise HTTPException(
                403, "only the requester may withdraw a write-set request")
        with runtime.db.lock:
            runtime.db.conn.execute(
                "DELETE FROM conversation_write_grant_requests WHERE conv_id=? AND id=?",
                (conv_id, request_id))
            runtime.db.conn.commit()
        await announce(conv_id, f"☏ write-set request for `{current.path}` "
                                f"withdrawn by @{principal.name}")
        return PendingWriteSetGrant(request=None)

