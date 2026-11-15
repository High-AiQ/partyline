"""Read-only computer-use totals with the same line/tree access as turn usage."""

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request

from .auth_guard import request_principal
from .computer_usage_contracts import ComputerUseSummary
from .computer_usage_summary import summary
from .hierarchy import descendants


def computer_usage_router(runtime):
    router = APIRouter()
    db = runtime.db

    @router.get("/api/telemetry/computer-use/summary", response_model=ComputerUseSummary)
    async def get_computer_usage(request: Request, conv_id: str,
                                 since: float = Query(0, ge=0, allow_inf_nan=False),
                                 include_descendants: bool = False):
        principal = request_principal(request)
        if principal.kind != "user" and conv_id not in {
                principal.conv_id, *descendants(db, principal.conv_id)}:
            raise HTTPException(403, "computer usage is limited to your line and descendants")
        if not db.get_conversation(conv_id):
            raise HTTPException(404, "no such line")
        ids = [conv_id, *(descendants(db, conv_id) if include_descendants else [])]
        return await asyncio.to_thread(summary, db, conv_id, ids, since, include_descendants)

    return router
