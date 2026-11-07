"""Agent control routes: request control, act inside the share, and the person's revoke."""

from fastapi import APIRouter, HTTPException, Request

from .auth_guard import request_principal
from .machine_scope import deny_unless, is_human
from .media import MediaError
from .screen_control_actions import ControlAction, describe
from .screen_frame_store import frame_reference


def control_router(runtime, hub, store) -> APIRouter:
    router = APIRouter()

    @router.post("/api/conversations/{conv_id}/screen-control/request")
    async def request_control(conv_id: str, request: Request):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "write")
        conv = runtime.db.get_conversation(conv_id)
        try:
            return await hub.control.request(conv_id, principal.name, conv["name"])
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/conversations/{conv_id}/screen-control/action")
    async def act(conv_id: str, body: ControlAction, request: Request):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "write")
        try:
            share, frame, cmd, stale = await hub.control.action(conv_id, principal.name, body)
            done = describe(cmd)
            ref, unchanged = (None, False)
            if body.frame != "none":
                ref, unchanged = await frame_reference(
                    store, share, principal.name, frame, frame.data, frame.mime)
        except (ValueError, TimeoutError) as exc:
            raise HTTPException(409, str(exc)) from exc
        except MediaError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        note = " The frame may predate the action; call screen_frame." if stale else ""
        result = {"done": done + note}
        if ref:
            tier = "thumb" if body.frame == "thumb" else "original"
            result["frame"] = getattr(ref.urls, tier)
            if unchanged:
                result["unchanged"] = True
        return result

    @router.delete("/api/screen/shares/{share_id}/control")
    async def revoke_control(share_id: str, request: Request):
        principal = request_principal(request)
        share = next((item for item in hub.shares.values() if item.share_id == share_id), None)
        if not is_human(principal) or not share or share.owner_id != principal.user_id:
            raise HTTPException(404, "screen share not found")
        if not await hub.control.revoke(share, f"revoked by {principal.name} in Partyline"):
            raise HTTPException(409, "agent control is not active on this share")
        return {"ok": True}

    return router
