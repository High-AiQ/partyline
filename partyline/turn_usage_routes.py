"""Read side of model usage telemetry; allowed on plain lines as well as captain trees."""

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from .auth_guard import request_principal
from .hierarchy import descendants
from .turn_usage_contracts import TurnSummary
from .turn_usage_summary import summary


def turn_usage_router(runtime):
    router = APIRouter()
    db = runtime.db

    @router.get("/api/telemetry/turns/summary", response_model=TurnSummary)
    async def get_turn_summary(request: Request, conv_id: str, since: float = Query(0, ge=0),
                               group: Literal["tool", "sub_op"] = "sub_op",
                               include_descendants: bool = False):
        principal = request_principal(request)
        if principal.kind != "user" and conv_id not in {
                principal.conv_id, *descendants(db, principal.conv_id)}:
            raise HTTPException(403, "model usage is limited to your line and descendants")
        if not db.get_conversation(conv_id):
            raise HTTPException(404, "no such line")
        ids = [conv_id, *(descendants(db, conv_id) if include_descendants else [])]
        return await asyncio.to_thread(summary, db, conv_id, ids, since, group, include_descendants)

    return router
