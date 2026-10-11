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
                attachment_id: str = "", turn: int | None = None) -> dict:
    stored_at = time.time()
    conv, _ = _storage_id(db, conv_id, scope)
    att = attachment_id if scope == "attachment" else ""
    db._exec(
        "INSERT OR REPLACE INTO line_notes"
        " (conv_id, scope, attachment_id, notes, updated_at, turn) VALUES (?,?,?,?,?,?)",
        (conv, scope, att, notes, stored_at, turn),
    )
    return {"scope": scope, "notes": notes, "updated_at": stored_at}


NOTES_NUDGE_EVERY_TURNS = 8
NOTES_STALE_SETTING = "notes_stale_turns"
NOTES_STALE_TURNS = 16
NUDGE = ("Update your attachment notes now: PUT "
         "$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/notes?scope=attachment")


def notes_nudge(db, conv_id: str, att_id: str, turns: int) -> str:
    """The wake-rider nudge: every N turns, when this worker's notes are M turns stale.

    The reliable route for finding 5.1: ``PreCompact`` stdout never reaches
    the model (Claude Code discards its output fields and no model turn runs
    between the hook and the compaction), so the prompt to write notes rides
    the wake instead — before any compaction, not at it. The counter is the
    harness's own turn count, so the rider keeps no state of its own. A
    worker that never wrote notes is the stalest case of all and is nudged
    too; the turn gate keeps that to once per N turns.
    """
    if turns <= 0 or turns % NOTES_NUDGE_EVERY_TURNS:
        return ""
    try:
        stale = int(db.get_setting(NOTES_STALE_SETTING) or NOTES_STALE_TURNS)
        row = db._exec(
            "SELECT turn FROM line_notes WHERE conv_id=? AND scope='attachment'"
            " AND attachment_id=?", (conv_id, att_id)).fetchone()
    except (AttributeError, ValueError):
        return ""  # a minimal db — the rider tests' fake — counts and stores nothing
    written_at = row["turn"] if row and row["turn"] is not None else 0
    return NUDGE if turns - written_at >= stale else ""


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
            # line notes are this line's captain's charge; tree notes live on
            # the root, so writing them needs the root's assign — otherwise a
            # grandchild's captain could overwrite the root's contracts.
            deny_unless(db, principal,
                        tree_root(db, conv_id) if scope == "tree" else conv_id, "assign")
        turn = None
        if scope == "attachment" and principal.attachment_id == target:
            # A process refreshing its own notes records the harness turn, so
            # the wake rider knows how stale they are (5.1). A person writing
            # someone else's notes leaves the turn unset.
            from .compaction_events import current_turns

            turn = current_turns(db, target)
        return write_notes(db, conv_id, scope, body.notes.strip(),
                           target if scope == "attachment" else "", turn)

    return router
