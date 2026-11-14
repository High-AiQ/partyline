"""Attachment-authenticated ingestion and line/tree tool usage reads."""

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from .auth_guard import request_principal
from .hierarchy import descendants
from .tool_telemetry import store, summary
from .tool_telemetry_contracts import ToolBatch, ToolIngest, UsageSummary


def telemetry_router(runtime):
    router = APIRouter()
    db = runtime.db

    @router.post("/api/telemetry/tool-calls", response_model=ToolIngest)
    async def ingest(request: Request, body: ToolBatch):
        principal = request_principal(request)
        if principal.kind != "machine":
            raise HTTPException(403, "tool telemetry requires an attachment credential")
        attachment = db.get_attachment(principal.attachment_id)
        return {"stored": await asyncio.to_thread(store, db, attachment, body.records)}

    @router.get("/api/telemetry/tool-calls/summary", response_model=UsageSummary)
    async def get_summary(request: Request, conv_id: str, since: float = Query(0, ge=0, allow_inf_nan=False),
                          group: Literal["tool", "sub_op"] = "sub_op",
                          include_descendants: bool = False):
        principal = request_principal(request)
        if principal.kind != "user" and conv_id not in {
                principal.conv_id, *descendants(db, principal.conv_id)}:
            raise HTTPException(403, "tool usage is limited to your line and descendants")
        if not db.get_conversation(conv_id):
            raise HTTPException(404, "no such line")
        ids = [conv_id, *(descendants(db, conv_id) if include_descendants else [])]
        return await asyncio.to_thread(summary, db, conv_id, ids, since, group, include_descendants)

    return router
