"""Authenticated stream of MCP tool-list revisions, pushed as they change."""

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .auth_guard import request_principal


def router_for(runtime):
    router = APIRouter()

    @router.get("/api/capability-stream")
    async def capability_stream(request: Request):
        """One JSON line now and one per change. The server never times the stream out;
        it ends when the client goes away or the server stops."""
        principal = request_principal(request)
        if principal.kind != "machine" or not principal.attachment_id:
            raise HTTPException(403, "capability versions are attachment-specific")
        versions = runtime.capability_versions

        async def lines():
            async for version in versions.changes(principal.attachment_id):
                current = runtime.db.get_attachment(principal.attachment_id)
                if current is None or current["status"] not in ("starting", "running"):
                    return  # its credential died with it; the bridge's next request gets the 401
                yield json.dumps({"version": version}) + "\n"

        return StreamingResponse(lines(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    return router
