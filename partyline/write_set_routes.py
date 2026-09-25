"""Per-line write-set scope: the recorded grants and their API.

The default write set — the line's cwd tree, its git binds, adapter
homes, the home caches — is derived at spawn, never stored. What is
stored here is the exception: extra scope a person or a captain above
the line granted, each row naming its grantor, so the record is the
audit trail and the room can see who widened what.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .auth_guard import request_principal
from .machine_scope import deny_unless, is_human


class WriteSetIn(BaseModel):
    path: str


class WriteSetGrant(BaseModel):
    path: str
    granted_by: str
    granted_at: float


def list_write_grants(db, conv_id: str) -> list[dict]:
    cur = db._exec("SELECT * FROM conversation_write_grants WHERE conv_id=? ORDER BY path",
                   (conv_id,))
    return [dict(r) for r in cur.fetchall()]


def add_write_grant(db, conv_id: str, path: str, granted_by: str) -> dict:
    """Record one granted path; re-granting an existing path is a no-op."""
    with db.lock:
        row = db.conn.execute(
            "SELECT * FROM conversation_write_grants WHERE conv_id=? AND path=?",
            (conv_id, path)).fetchone()
        if row is None:
            db.conn.execute(
                "INSERT INTO conversation_write_grants(conv_id,path,granted_by,granted_at) "
                "VALUES(?,?,?,?)", (conv_id, path, granted_by, time.time()))
            db.conn.commit()
            row = db.conn.execute(
                "SELECT * FROM conversation_write_grants WHERE conv_id=? AND path=?",
                (conv_id, path)).fetchone()
    return dict(row)


def write_set_router(runtime) -> APIRouter:
    from .write_set_requests import file_write_set_request, make_announcer

    router = APIRouter()

    @router.get("/api/conversations/{conv_id}/write-set",
                response_model=list[WriteSetGrant])
    async def list_write_set(request: Request, conv_id: str):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "read")
        return list_write_grants(runtime.db, conv_id)

    @router.post("/api/conversations/{conv_id}/write-set")
    async def grant_or_request_write_set(request: Request, conv_id: str, body: WriteSetIn):
        from .system_notice import post_system_notice
        db = runtime.db
        principal = request_principal(request)
        if db.get_conversation(conv_id) is None:
            raise HTTPException(404)
        if is_human(principal):
            path = body.path.strip()
            if not path.startswith("/") or path == "/" or os.path.normpath(path) != path:
                raise HTTPException(
                    400, "path must be an absolute, normalized file or directory path")
            add_write_grant(db, conv_id, path, principal.name)
            await post_system_notice(
                runtime, conv_id, f"☏ write-set grant for `{path}` by @{principal.name}",
                actor=principal)
            return list_write_grants(db, conv_id)
        return await file_write_set_request(
            runtime, conv_id, body.path, principal, announce_fn=make_announcer(runtime))

    return router
