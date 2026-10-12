"""Per-line write-set scope: the recorded grants and their API.

The protected repositories and Partyline database are derived at spawn,
never stored. What is stored here is the exception: extra writable scope
a person or a captain above the line granted, each row naming its
grantor, so the record is the audit trail and the room can see who
widened what.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth_guard import request_principal
from .machine_scope import deny_unless, is_human


class WriteSetIn(BaseModel):
    path: str = ""
    # Or name a review worktree instead of typing its path: the pair resolves
    # to ``<repository>/.review/<full sha>``, the repository under the same
    # subtree rule a review worktree obeys. The pair and a typed path are
    # exclusive; so are half a pair and empty hands.
    repository: str = Field(default="", max_length=4096)
    sha: str = Field(default="", max_length=64)


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
    from .write_set_decisions import make_announcer
    from .write_set_requests import file_write_set_request, resolve_write_set_path

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
            # Same rule as a process filing: the path must be grantable, so a
            # person cannot record a grant the fence would drop at spawn (2.18).
            from .write_set_requests import validate_grantable
            path = validate_grantable(db, resolve_write_set_path(db, conv_id, body))
            add_write_grant(db, conv_id, path, principal.name)
            await post_system_notice(
                runtime, conv_id, f"☏ write-set grant for `{path}` by @{principal.name}",
                actor=principal)
            return list_write_grants(db, conv_id)
        return await file_write_set_request(
            runtime, conv_id, resolve_write_set_path(db, conv_id, body), principal,
            announce_fn=make_announcer(runtime))

    return router
