"""Authenticated long-poll endpoint for MCP tool-list changes."""

from fastapi import APIRouter, HTTPException, Query, Request

from .auth_guard import request_principal


def router_for(runtime):
    router = APIRouter()

    @router.get("/api/capability-version")
    async def capability_version(request: Request, since: str | None = Query(default=None, max_length=64)):
        principal = request_principal(request)
        if principal.kind != "machine" or not principal.attachment_id:
            raise HTTPException(403, "capability versions are attachment-specific")
        versions = runtime.capability_versions
        current = versions.current(principal.attachment_id)
        if since != current:
            return {"version": current}
        current = await versions.wait_for_change(principal.attachment_id, since, timeout=55)
        return {"version": current}

    return router
