"""Person-only, line-scoped access to the durable screen audit."""
import json
import re

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from .auth_guard import request_principal
from .machine_scope import deny_unless, is_human


class WindowAccessEntry(BaseModel):
    agent: str
    call: str
    app: str
    title: str
    result: str
    time: float
    entry_hash: str


class WindowAccessAuditResponse(BaseModel):
    entries: list[WindowAccessEntry]
    chain_head: str | None


class ScreenAccessEntry(BaseModel):
    chain_id: str
    agent: str
    detail: str
    time: float
    previous_hash: str
    entry_hash: str


class ScreenAccessAuditResponse(BaseModel):
    entries: list[ScreenAccessEntry]
    next_before: int | None


def _visible_detail(entry: str) -> str:
    # Older monitor actions saved a bounded preview. Keep the original hash and row.
    if entry.startswith("type \x60"):
        match = re.match(r"type \x60[^\x60]*\x60 \((\d+) chars\)(?: \((unconfirmed|interrupted))?", entry)
        if not match:
            return "type"
        count, outcome = match.groups()
        return f"type ({count} chars)" + (f" ({outcome})" if outcome else "")
    if entry.startswith("{"):
        metadata = json.loads(entry)
        # The local file-input log records absolute paths for its own audit.
        if metadata.get("operation") == "set_files" and "paths" in metadata:
            metadata.pop("paths", None)
            return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    return entry


def _entry(row):
    call, _, rest = row["entry"].partition(": ")
    app_title, _, result = rest.rpartition(" (")
    app, _, title = app_title.partition(" — ")
    return WindowAccessEntry(agent=row["agent"], call=call, app=app, title=title,
                             result=result.removesuffix(")"), time=row["created_at"],
                             entry_hash=row["entry_hash"])


def audit_router(runtime):
    router = APIRouter()

    def check_access(request: Request, conv_id: str):
        principal = request_principal(request)
        if not is_human(principal):
            raise HTTPException(403, "screen access audit is visible to people")
        deny_unless(runtime.db, principal, conv_id, "read")

    @router.get("/api/conversations/{conv_id}/screen-access-audit",
                response_model=ScreenAccessAuditResponse)
    async def screen_access_audit(conv_id: str, request: Request,
                                  before: int | None = Query(default=None, ge=1, le=2**63 - 1),
                                  limit: int = Query(default=50, ge=1, le=200)):
        check_access(request, conv_id)
        where, args = ("conv_id=? AND id<?", (conv_id, before)) if before is not None else (
            "conv_id=?", (conv_id,))
        rows = runtime.db._exec(
            f"SELECT * FROM screen_control_audit WHERE {where} ORDER BY id DESC LIMIT ?",
            (*args, limit + 1),
        ).fetchall()
        return ScreenAccessAuditResponse(
            entries=[ScreenAccessEntry(
                chain_id=row["share_id"], agent=row["agent"], detail=_visible_detail(row["entry"]),
                time=row["created_at"], previous_hash=row["previous_hash"], entry_hash=row["entry_hash"],
            ) for row in rows[:limit]],
            next_before=rows[limit - 1]["id"] if len(rows) > limit else None,
        )

    @router.get("/api/conversations/{conv_id}/window-access-audit",
                response_model=WindowAccessAuditResponse)
    async def window_access_audit(conv_id: str, request: Request,
                                  limit: int = Query(default=50, ge=1, le=200)):
        check_access(request, conv_id)
        share_id = "window-access:" + conv_id
        head = runtime.db._exec("SELECT entry_hash FROM screen_control_audit WHERE share_id=? "
                                "ORDER BY id DESC LIMIT 1", (share_id,)).fetchone()
        rows = runtime.db._exec("SELECT * FROM screen_control_audit WHERE share_id=? "
                                "ORDER BY id DESC LIMIT ?", (share_id, limit)).fetchall()
        return WindowAccessAuditResponse(entries=[_entry(row) for row in rows],
                                         chain_head=head["entry_hash"] if head else None)

    return router
