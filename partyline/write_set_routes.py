"""Per-line write-set scope: the recorded grants and their API.

The protected repositories and Partyline database are derived at spawn,
never stored. What is stored here is the exception: extra writable scope
a person or a captain above the line granted, each row naming its
grantor, so the record is the audit trail and the room can see who
widened what.
"""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import docker_relay, docker_workloads
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
    docker_mode: Literal["", "managed", "unrestricted"] = ""  # docker access only; a person's choice


class WriteSetGrant(BaseModel):
    path: str
    granted_by: str
    granted_at: float
    docker_mode: str = "managed"


def list_write_grants(db, conv_id: str) -> list[dict]:
    cur = db._exec("SELECT * FROM conversation_write_grants WHERE conv_id=? ORDER BY path",
                   (conv_id,))
    return [dict(r) for r in cur.fetchall()]


def load_write_grants(db, att: dict) -> None:
    """Load a spawning attachment's grants; the docker grant starts its relay."""
    att["write_grants"] = list_write_grants(db, att["conv_id"])
    att["docker_relays_exist"] = docker_relay.any_grant(db)
    docker_relay.prepare(att)


def add_write_grant(db, conv_id: str, path: str, granted_by: str, docker_mode: str | None = None) -> dict:
    """Record one granted path; re-granting is a no-op, except a person naming a docker mode."""
    with db.lock:
        row = db.conn.execute(
            "SELECT * FROM conversation_write_grants WHERE conv_id=? AND path=?",
            (conv_id, path)).fetchone()
        if row is not None and docker_mode and row["docker_mode"] != docker_mode:
            docker_relay.disconnect(conv_id)  # open connections were made under the old policy
            db.conn.execute("UPDATE conversation_write_grants SET docker_mode=? WHERE conv_id=? AND path=?",
                            (docker_mode, conv_id, path))
            db.conn.commit()
            row = db.conn.execute("SELECT * FROM conversation_write_grants WHERE conv_id=? AND path=?",
                                  (conv_id, path)).fetchone()
        if row is None:
            db.conn.execute(
                "INSERT INTO conversation_write_grants(conv_id,path,granted_by,granted_at,docker_mode) "
                "VALUES(?,?,?,?,?)", (conv_id, path, granted_by, time.time(), docker_mode or "managed"))
            db.conn.commit()
            row = db.conn.execute(
                "SELECT * FROM conversation_write_grants WHERE conv_id=? AND path=?",
                (conv_id, path)).fetchone()
    return dict(row)


def write_set_router(runtime, resume=None) -> APIRouter:
    from .write_set_decisions import make_announcer
    from .write_set_requests import (
        file_write_set_request, resolve_write_set_path, resume_granted_scope)

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
            add_write_grant(db, conv_id, path, principal.name, body.docker_mode or None)
            text = f"☏ write-set grant for `{path}` by @{principal.name}"
            if resume is not None and docker_relay.is_docker_socket(path):
                # Every live process must pick up the mount that hides the relays.
                _done, failed = await resume_granted_scope(runtime, conv_id, path, resume)
                text = (f"☏ {docker_workloads.mode_text(body.docker_mode or 'managed')} granted by "
                        f"@{principal.name} — every live process is resumed so other lines "
                        "cannot reach the relay")
                if failed:
                    text += f" — could not resume @{', @'.join(failed)}; re-attach them by hand"
            await post_system_notice(runtime, conv_id, text, actor=principal)
            return list_write_grants(db, conv_id)
        if body.docker_mode:
            raise HTTPException(403, "only a person chooses a docker access mode")
        return await file_write_set_request(
            runtime, conv_id, resolve_write_set_path(db, conv_id, body), principal,
            announce_fn=make_announcer(runtime))

    return router
