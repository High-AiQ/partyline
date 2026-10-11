"""The line notebook: durable notes that survive compaction and restarts.

Finding 2.13's durable half. After any compaction a process keeps only what
its summary kept — the acceptance criteria, the SHA it was told to merge, the
gates it already ran — and nothing survives a restart at all. These notes are
the partyline-side record: three scopes (the tree's contracts, the line's
charge, the process's own working state), stored in the database, rendered
back into the post-compaction re-briefing.

The write rule follows the hierarchy, one line each: the captain keeps the
``line`` and ``tree`` scopes (they are its charge to persist), each process
writes its own ``attachment`` notes, and a person writes any of them. Reads
need only ``read`` on the line — notes exist to be seen after a failure.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .auth_guard import request_principal
from .hierarchy import ancestors
from .machine_scope import deny_unless, is_human

NOTE_LIMIT = 4000
SCOPES = ("line", "attachment", "tree")


class NotesIn(BaseModel):
    notes: str = Field(default="", max_length=NOTE_LIMIT)


def tree_root(db, conv_id: str) -> str:
    """The root line of conv_id's tree; tree-scoped notes are stored there."""
    lineage = ancestors(db, conv_id)
    return lineage[-1] if lineage else conv_id


def _storage_id(db, conv_id: str, scope: str) -> tuple[str, str]:
    """(conv_id, attachment_id) this scope is stored under."""
    if scope == "tree":
        return tree_root(db, conv_id), ""
    return conv_id, ""


def read_notes(db, conv_id: str, scope: str, attachment_id: str = "") -> dict:
    if scope != "attachment":
        attachment_id = ""  # only the attachment scope is keyed by process
    conv, _ = _storage_id(db, conv_id, scope)
    row = db._exec(
        "SELECT notes, updated_at FROM line_notes WHERE conv_id=? AND scope=?"
        " AND attachment_id=?", (conv, scope, attachment_id),
    ).fetchone()
    return {"scope": scope, "notes": row["notes"] if row else "",
            "updated_at": row["updated_at"] if row else None}


def write_notes(db, conv_id: str, scope: str, notes: str,
                attachment_id: str = "") -> dict:
    stored_at = time.time()
    conv, _ = _storage_id(db, conv_id, scope)
    att = attachment_id if scope == "attachment" else ""
    db._exec(
        "INSERT OR REPLACE INTO line_notes"
        " (conv_id, scope, attachment_id, notes, updated_at) VALUES (?,?,?,?,?)",
        (conv, scope, att, notes, stored_at),
    )
    return {"scope": scope, "notes": notes, "updated_at": stored_at}


def notes_router(runtime) -> APIRouter:
    router = APIRouter()

    @router.get("/api/conversations/{conv_id}/notes")
    async def get_notes(request: Request, conv_id: str,
                        scope: str = Query(default="line"), attachment_id: str = ""):
        db = runtime.db
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "read")
        if scope not in SCOPES:
            raise HTTPException(404, f"unknown notes scope: {scope}")
        if scope == "attachment" and not attachment_id and principal.attachment_id:
            attachment_id = principal.attachment_id  # a process reads its own by default
        return read_notes(db, conv_id, scope, attachment_id)

    @router.put("/api/conversations/{conv_id}/notes")
    async def put_notes(request: Request, conv_id: str, body: NotesIn,
                        scope: str = Query(default="line"), attachment_id: str = ""):
        db = runtime.db
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "read")
        if scope not in SCOPES:
            raise HTTPException(404, f"unknown notes scope: {scope}")
        if scope == "attachment":
            # A process writes only its own notes; a person may write any.
            target = attachment_id or principal.attachment_id or ""
            if not is_human(principal) and target != principal.attachment_id:
                raise HTTPException(403, "a process may write only its own notes")
            if not target:
                raise HTTPException(400, "name the attachment whose notes these are")
        elif not is_human(principal):
            # line and tree are the captain's charge to persist.
            deny_unless(db, principal, conv_id, "assign")
        return write_notes(db, conv_id, scope, body.notes.strip(), target
                           if scope == "attachment" else "")

    return router
