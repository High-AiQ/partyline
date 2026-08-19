"""REST routes for path-glob write claims."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .auth_guard import request_principal
from .claims import (
    Claim,
    ClaimConflict,
    ClaimIn,
    ClaimTaken,
    create_claim,
    list_claims,
    purge_claims,
    release_claim,
)


def claims_router(runtime) -> APIRouter:
    router = APIRouter()

    def require_line(conv_id: str):
        conv = runtime.db.get_conversation(conv_id)
        if not conv:
            raise HTTPException(404)
        return conv

    @router.post("/api/conversations/{conv_id}/claims", response_model=Claim)
    async def post_claim(request: Request, conv_id: str, body: ClaimIn):
        require_line(conv_id)
        # The owner is the authenticated caller — a client-supplied owner
        # would let any valid token claim paths as any handle.
        owner = request_principal(request).name
        try:
            return create_claim(runtime.db, conv_id, owner, body.paths)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except ClaimTaken as exc:
            raise HTTPException(
                409,
                ClaimConflict(
                    detail=str(exc), conflict=exc.conflict
                ).model_dump(),
            ) from exc

    @router.get("/api/conversations/{conv_id}/claims", response_model=list[Claim])
    async def get_claims(conv_id: str):
        require_line(conv_id)
        return list_claims(runtime.db, conv_id)

    @router.delete("/api/claims/{claim_id}", response_model=dict)
    async def delete_claim(request: Request, claim_id: str, force: bool = False):
        # Your own claims release freely. Releasing someone else's needs the
        # explicit ?force=true — a named override for stale locks (claims
        # also expire on their own), never an impersonated owner.
        owner = None if force else request_principal(request).name
        try:
            gone = release_claim(runtime.db, claim_id, owner)
        except PermissionError as exc:
            raise HTTPException(
                403, f"claim belongs to {exc}; pass force=true to override"
            ) from exc
        if not gone:
            raise HTTPException(404)
        return {"ok": True}

    return router


__all__ = ["claims_router", "purge_claims"]
