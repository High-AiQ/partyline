"""A line asks for extra write scope; a person approves it in a banner.

The default write set is derived at spawn. When work needs a path outside it,
a process on the line — or a captain above — files a request; every open tab
on that line shows it, and a person approves or declines. Approval records
the grant, rings the requester, and resumes the line's live processes so the
widened bind applies without a service restart.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .auth_guard import request_principal
from .contracts import WriteSetGrantRequestEvent
from .hierarchy import ancestors
from .line_process_routes import detach_attachment, live_attachments
from .machine_scope import deny_unless, is_human
from .mention_relay import post_private
from .resume_continuation import resume_with_backlog
from .system_notice import post_system_notice
from .write_set_routes import add_write_grant

logger = logging.getLogger(__name__)


class WriteSetGrantRequest(BaseModel):
    id: str
    conversation_id: str
    path: str
    requester: str
    requester_attachment_id: str | None = None
    created_at: float


class PendingWriteSetGrant(BaseModel):
    request: WriteSetGrantRequest | None = None


def get_pending_request(db, conv_id: str) -> dict | None:
    row = db._exec(
        "SELECT * FROM conversation_write_grant_requests WHERE conv_id=?",
        (conv_id,),
    ).fetchone()
    return dict(row) if row else None


def _row_to_request(row: dict) -> WriteSetGrantRequest:
    return WriteSetGrantRequest(
        id=row["id"],
        conversation_id=row["conv_id"],
        path=row["path"],
        requester=row["requester"],
        requester_attachment_id=row["requester_attachment_id"],
        created_at=row["created_at"],
    )


def pending_model(db, conv_id: str) -> PendingWriteSetGrant:
    row = get_pending_request(db, conv_id)
    return PendingWriteSetGrant(request=_row_to_request(row) if row else None)


def machine_may_file(db, principal, conv_id: str) -> bool:
    return principal.conv_id == conv_id or (
        principal.is_lead and principal.conv_id in ancestors(db, conv_id)
    )


def validate_path(path: str) -> str:
    import os

    path = path.strip()
    if not path.startswith("/") or path == "/" or os.path.normpath(path) != path:
        raise HTTPException(
            400, "path must be an absolute, normalized file or directory path")
    return path


async def resume_line_attachments(runtime, conv_id: str, resume) -> tuple[list[str], list[str]]:
    """Detach and resume every live attachment on one line, best-effort."""
    live = live_attachments(runtime.db, conv_id, include_children=False)
    att_ids = [att["id"] for att in live]
    names = {att["id"]: att["name"] for att in live}
    resumed: list[str] = []
    failed: list[str] = []
    for att_id in att_ids:
        try:
            await detach_attachment(runtime, att_id)
        except Exception:
            logger.exception("write-set approval could not detach %s on %s", att_id, conv_id)
            failed.append(names[att_id])
            continue
        try:
            await resume_with_backlog(runtime, att_id, resume)
        except Exception:
            logger.exception("write-set approval could not resume %s on %s", att_id, conv_id)
            failed.append(names[att_id])
        else:
            resumed.append(att_id)
    return resumed, failed


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

    def _take(request: Request, conv_id: str, request_id: str) -> WriteSetGrantRequest:
        if not is_human(request_principal(request)):
            raise HTTPException(403, "only a person may decide a write-set request")
        current = pending_model(runtime.db, conv_id).request
        if current is None or current.id != request_id:
            raise HTTPException(404, "that write-set request is no longer pending")
        return current

    @app.post("/api/conversations/{conv_id}/write-set/request/{request_id}/approve",
              response_model=PendingWriteSetGrant)
    async def approve(request: Request, conv_id: str, request_id: str):
        current = _take(request, conv_id, request_id)
        principal = request_principal(request)
        who = principal.name
        add_write_grant(runtime.db, conv_id, current.path, who)
        with runtime.db.lock:
            runtime.db.conn.execute(
                "DELETE FROM conversation_write_grant_requests WHERE conv_id=? AND id=?",
                (conv_id, request_id))
            runtime.db.conn.commit()
        _resumed, failed = await resume_line_attachments(runtime, conv_id, resume)
        text = (f"☏ write-set grant for `{current.path}` approved by @{who} — "
                "live processes on this line are resumed with the widened bind")
        if failed:
            text += (f" — could not resume @{', @'.join(failed)}; "
                     "re-attach them by hand")
        await announce(conv_id, text)
        await ring_requester(current, text, actor=principal)
        return PendingWriteSetGrant(request=None)

    @app.delete("/api/conversations/{conv_id}/write-set/request/{request_id}",
                 response_model=PendingWriteSetGrant)
    async def decline(request: Request, conv_id: str, request_id: str):
        current = _take(request, conv_id, request_id)
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


async def file_write_set_request(
    runtime, conv_id: str, path: str, principal, *, announce_fn,
) -> WriteSetGrantRequest:
    db = runtime.db
    if get_pending_request(db, conv_id) is not None:
        raise HTTPException(409, "a write-set request is already waiting for a person")
    if not machine_may_file(db, principal, conv_id):
        raise HTTPException(
            403, "only a person or a captain above this line may grant write scope")
    path = validate_path(path)
    request = WriteSetGrantRequest(
        id=uuid.uuid4().hex[:12],
        conversation_id=conv_id,
        path=path,
        requester=principal.name,
        requester_attachment_id=principal.attachment_id,
        created_at=time.time(),
    )
    with db.lock:
        db.conn.execute(
            "INSERT INTO conversation_write_grant_requests"
            "(conv_id,id,path,requester,requester_attachment_id,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (conv_id, request.id, path, request.requester,
             request.requester_attachment_id, request.created_at))
        db.conn.commit()
    await announce_fn(
        conv_id,
        f"☏ @{principal.name} asks a person to grant write-set scope for `{path}` — "
        "approve or decline from the banner",
        actor=principal,
    )
    return request
