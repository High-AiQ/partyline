"""Pairing, user controls, helper WebSocket, and MCP frame persistence."""

import asyncio
import base64
import io
import time

from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel, ValidationError
from PIL import Image, ImageDraw

from .helper_release import update_available
from .auth_guard import bearer_token, request_principal
from .machine_scope import deny_unless, is_human
from .media import MediaError, MediaStore
from .screen_audit import recover
from .screen_connections import revoke as revoke_device
from .local_tools_audit import recover as recover_tools
from .local_tools_routes import tools_router
from .render_check_routes import render_check_router
from .screen_control_routes import control_router
from .screen_frame_store import frame_reference
from .screen_hub import ScreenHub
from .screen_protocol import PairClaim, Region
from .screen_pointer import captured_pointer, annotate_stationary_pointers


class ShareStart(BaseModel):
    device_id: str
    region: Region
    walkthrough: bool = False
    control: bool = False


def register_screen_routes(app, runtime, store: MediaStore) -> ScreenHub:
    recover(runtime.db)
    recover_tools(runtime.db)
    hub = ScreenHub(runtime)
    app.state.screen_hub = hub
    runtime.screen_hub = hub
    router = APIRouter()

    @router.post("/api/screen/pair")
    async def pair(request: Request, conv_id: str):
        principal = request_principal(request)
        if not is_human(principal) or not runtime.db.get_conversation(conv_id):
            raise HTTPException(403, "screen helper pairing is available to people on a line")
        if not hub.limits.issue(principal.user_id):
            raise HTTPException(429, "too many pairing codes; try again later")
        code = hub.issue_pair_code(principal.user_id, conv_id)
        return {"code": code, "expires_in": 300}

    @router.post("/api/screen/pair/claim")
    async def claim(request: Request):
        ip = request.client.host if request.client else "unknown"
        if not hub.limits.claim(ip, ""):
            raise HTTPException(429, "too many pairing attempts; try again later")
        try:
            payload = await request.json()
        except ValueError as exc:
            raise HTTPException(400, "invalid pairing request") from exc
        code = payload.get("code") if isinstance(payload, dict) else None
        code = code if isinstance(code, str) and 0 < len(code) <= 8 else ""
        if code and hub.limits.locked(code):
            raise HTTPException(429, "too many pairing attempts; try again later")
        try:
            body = PairClaim.model_validate(payload)
        except ValidationError as exc:
            if code:
                hub.limits.failed(code)
            raise HTTPException(400, "invalid pairing request") from exc
        if not body.device_name.strip() or not body.os.strip():
            hub.limits.failed(body.code)
            raise HTTPException(400, "device name and OS are required")
        result = hub.claim_pair_code(body.code, body.device_name, body.os)
        if not result:
            hub.limits.failed(body.code)
            raise HTTPException(400, "pairing code is invalid, expired, or already used")
        device_id, token, _, _ = result
        return {"device_id": device_id, "token": token}

    @router.get("/api/screen/devices")
    async def devices(request: Request, conv_id: str):
        principal = request_principal(request)
        if not is_human(principal):
            raise HTTPException(403, "screen devices are visible to their owner")
        rows = runtime.db._exec(
            "SELECT id,name,os,created_at FROM screen_devices WHERE owner_id=? AND conv_id=? "
            "AND revoked_at IS NULL ORDER BY created_at", (principal.user_id, conv_id)
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            online = hub.devices.get(item["id"])
            item["online"] = online is not None
            item["monitors"] = online["monitors"] if online else []
            item["helper_version"] = online["helper_version"] if online else None
            item["update_available"] = bool(online) and update_available(online["helper_version"])
            result.append(item)
        return {"devices": result}

    @router.delete("/api/screen/devices/{device_id}")
    async def revoke(device_id: str, request: Request):
        principal = request_principal(request)
        if not is_human(principal):
            raise HTTPException(403, "screen devices are managed by their owner")
        row = runtime.db._exec(
            "SELECT id FROM screen_devices WHERE id=? AND owner_id=? AND revoked_at IS NULL",
            (device_id, principal.user_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "computer not found")
        runtime.db._exec("UPDATE screen_devices SET revoked_at=? WHERE id=?",
                         (time.time(), device_id))
        await revoke_device(hub, device_id)
        return {"ok": True}

    @router.post("/api/screen/shares")
    async def start_share(body: ShareStart, request: Request, conv_id: str):
        principal = request_principal(request)
        if not is_human(principal):
            raise HTTPException(403, "only a person can start a screen share")
        conv = runtime.db.get_conversation(conv_id)
        if not conv:
            raise HTTPException(404, "line not found")
        row = runtime.db._exec(
            "SELECT 1 FROM screen_devices WHERE id=? AND owner_id=? AND conv_id=? AND revoked_at IS NULL",
            (body.device_id, principal.user_id, conv_id),
        ).fetchone()
        if not row:
            raise HTTPException(403, "computer is not paired to this line")
        try:
            if body.control and hub.devices.get(body.device_id, {}).get("control", 0) < 1:
                raise ValueError("helper too old for control: update partyline-helper on that computer")
            share = await hub.start_share(conv_id, principal.user_id, principal.name,
                                          body.device_id, body.region.model_dump(), conv["name"],
                                          walkthrough=body.walkthrough, control=body.control)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"share_id": share.share_id, "status": share.status}

    @router.delete("/api/screen/shares/{share_id}")
    async def stop_share(share_id: str, request: Request):
        principal = request_principal(request)
        share = next((item for item in hub.shares.values() if item.share_id == share_id), None)
        if not is_human(principal) or not share or share.owner_id != principal.user_id:
            raise HTTPException(404, "screen share not found")
        await hub.stop_share(share_id)
        return {"ok": True}

    @router.post("/api/screen/preview")
    async def preview(request: Request, device_id: str, monitor_id: str):
        principal = request_principal(request)
        if not is_human(principal):
            raise HTTPException(403, "only a person can preview a monitor")
        try:
            item = await hub.preview(device_id, principal.user_id, monitor_id)
        except (TimeoutError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return {**{key: value for key, value in item.items() if key != "data"},
                "data": base64.b64encode(item["data"]).decode("ascii")}

    @router.get("/api/screen/shares")
    async def current_share(request: Request, conv_id: str):
        deny_unless(runtime.db, request_principal(request), conv_id, "read")
        share = hub.shares.get(conv_id)
        device = hub.devices.get(share.device_id) if share else None
        return {"share": hub._share_view(share, device)["share"] if share and device else None}

    @router.post("/api/conversations/{conv_id}/screen-frame")
    async def mcp_frame(conv_id: str, request: Request, mark_pointer: bool = False):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "read")
        share = hub.shares.get(conv_id)
        if share and share.share_id in hub.walkthroughs.items:
            raise HTTPException(409, "screen frames are unavailable while a walkthrough is in progress")
        try:
            share, frame = await hub.capture(conv_id)
            history = [item for item in share.frames if item.sequence < frame.sequence] + [frame]
            frame = (await asyncio.to_thread(annotate_stationary_pointers, history))[-1]
            data = _mark_pointer(frame) if mark_pointer else frame.data
            mime = "image/png" if mark_pointer and pointer_coordinates(frame)["frame"] else frame.mime
            ref, unchanged = await frame_reference(store, share, principal.name, frame, data, mime,
                                           marked=mark_pointer)
        except (ValueError, TimeoutError) as exc:
            raise HTTPException(409, str(exc)) from exc
        except MediaError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        return {"file": ref.model_dump(mode="json"), "description": frame_detail(frame),
                "share_id": share.share_id, "unchanged": unchanged}

    @app.websocket("/api/screen/helper")
    async def helper_socket(ws: WebSocket):
        token = bearer_token(ws.headers, ws.query_params)
        digest = hub.digest(token)
        row = runtime.db._exec(
            "SELECT * FROM screen_devices WHERE token_hash=? AND revoked_at IS NULL", (digest,)
        ).fetchone()
        if not row:
            await ws.accept()
            await ws.close(code=4401, reason="invalid helper token")
            return
        await hub.connect(ws, dict(row))

    from .screen_elements import elements_router
    app.include_router(elements_router(runtime, hub))
    app.include_router(router)
    app.include_router(control_router(runtime, hub, store))
    app.include_router(tools_router(runtime, hub, store))
    app.include_router(render_check_router(runtime, hub, store))
    from .walkthrough_routes import walkthrough_router
    app.include_router(walkthrough_router(runtime, hub, store))
    return hub


def pointer_coordinates(frame):
    pointer, region = frame.pointer, frame.region
    if captured_pointer(frame):
        return {"os": None, "frame": {"x": frame.out_width // 2, "y": frame.out_height // 2}}
    if not pointer or not pointer.get("visible"):
        return {"os": None, "frame": None}
    x, y = pointer["x"], pointer["y"]
    if not (region["x"] <= x < region["x"] + region["width"]
            and region["y"] <= y < region["y"] + region["height"]):
        return {"os": None, "frame": None}
    fx = min(frame.out_width - 1, int((x - region["x"]) * frame.out_width / region["width"]))
    fy = min(frame.out_height - 1, int((y - region["y"]) * frame.out_height / region["height"]))
    return {"os": {"x": x, "y": y}, "frame": {"x": fx, "y": fy}}


def frame_detail(frame) -> str:
    return (f"region={frame.region}; output={frame.out_width}x{frame.out_height}; "
            f"pointer={pointer_coordinates(frame)}" +
            (" (view centre; pointer captured)" if captured_pointer(frame) else
             " (pointer stationary)" if frame.pointer and frame.pointer.get("stationary") else ""))


def _mark_pointer(frame):
    coordinates = pointer_coordinates(frame)["frame"]
    image = Image.open(io.BytesIO(frame.data)).convert("RGB")
    if coordinates is None:
        return frame.data
    x, y = coordinates["x"], coordinates["y"]
    draw = ImageDraw.Draw(image)
    draw.ellipse((x - 15, y - 15, x + 15, y + 15), outline="white", width=4)
    draw.ellipse((x - 15, y - 15, x + 15, y + 15), outline="black", width=2)
    for width, color in ((5, "black"), (2, "white")):
        draw.line((x - 24, y, x + 24, y), fill=color, width=width)
        draw.line((x, y - 24, x, y + 24), fill=color, width=width)
    label = ("view centre" if captured_pointer(frame) else
             f"{frame.pointer['x']},{frame.pointer['y']}")
    draw.text((x + 20, y + 20), label, fill="yellow",
              stroke_width=2, stroke_fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
