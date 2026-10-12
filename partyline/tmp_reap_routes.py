"""Root-captain or person reap of leftover attachment temp dirs (5.12).

Closes and purges reap their own directories as they happen; this endpoint
is the captain's broom for everything that slipped past those moments —
crash leftovers and rows deleted before the finding existed. It only ever
deletes the directory of an attachment id with no row at all: live,
detached and exited rows can all resume, so their directories stay.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from .attachment_tmp import reap_missing_tmp
from .auth_guard import request_principal
from .hierarchy import lead_attachment
from .machine_scope import is_human
from .resource_budget import family_roots

LIVE = ("starting", "running")


def register_tmp_reap_routes(app: FastAPI, runtime) -> None:
    @app.post("/api/conversations/{conv_id}/tmp/reap")
    async def reap_tmp(request: Request, conv_id: str):
        db = runtime.db
        principal = request_principal(request)
        if not is_human(principal):
            if family_roots(db).get(conv_id, (None, None))[0] != principal.conv_id:
                raise HTTPException(403, "only the root captain or a person may reap")
            if not principal.is_lead:
                raise HTTPException(403, "only the root captain or a person may reap")
            lead = lead_attachment(db, principal.conv_id)
            if (lead is None or lead["id"] != principal.attachment_id
                    or lead["status"] not in LIVE):
                raise HTTPException(
                    403, "only the live root captain or a person may reap")
        freed, reaped = reap_missing_tmp(db)
        return {"ok": True, "freed_bytes": freed, "reaped": reaped}
