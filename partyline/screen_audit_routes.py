"""Person-only access to the durable standing window-access audit."""
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


def _entry(row):
    call, _, rest = row["entry"].partition(": ")
    app_title, _, result = rest.rpartition(" (")
    app, _, title = app_title.partition(" — ")
    return WindowAccessEntry(agent=row["agent"], call=call, app=app, title=title,
                             result=result.removesuffix(")"), time=row["created_at"],
                             entry_hash=row["entry_hash"])


def audit_router(runtime):
    router = APIRouter()

    @router.get("/api/conversations/{conv_id}/window-access-audit",
                response_model=WindowAccessAuditResponse)
    async def window_access_audit(conv_id: str, request: Request,
                                  limit: int = Query(default=50, ge=1, le=200)):
        principal = request_principal(request)
        if not is_human(principal):
            raise HTTPException(403, "window access audit is visible to people")
        deny_unless(runtime.db, principal, conv_id, "read")
        share_id = "window-access:" + conv_id
        head = runtime.db._exec("SELECT entry_hash FROM screen_control_audit WHERE share_id=? "
                                "ORDER BY id DESC LIMIT 1", (share_id,)).fetchone()
        rows = runtime.db._exec("SELECT * FROM screen_control_audit WHERE share_id=? "
                                "ORDER BY id DESC LIMIT ?", (share_id, limit)).fetchall()
        return WindowAccessAuditResponse(entries=[_entry(row) for row in rows],
                                         chain_head=head["entry_hash"] if head else None)

    return router
