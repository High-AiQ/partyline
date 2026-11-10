"""Authenticated native helper connections and ephemeral screen shares."""

import asyncio
import hashlib
import json
import secrets
import time
import uuid

from pydantic import ValidationError

from fastapi import WebSocket, WebSocketDisconnect

from .screen_connections import device_valid
from .local_tools import TOOL_MESSAGES, LocalTools
from .screen_control import CONTROL_MESSAGES, ControlHub
from .capability_versions import bump_runtime
from .screen_frames import BufferedFrame, ShareBuffer
from .screen_share_frames import add_frame
from .screen_share_stop import stop_share as stop_screen_share
from .screen_elements import ElementsHub
from .screen_window_grants import MESSAGES as WINDOW_MESSAGES, WindowGrants
from .screen_pair_limits import PairLimits
from .screen_requests import capture, preview
from .walkthrough_takes import Takes
from .screen_protocol import (
    DEFAULT_LONG_EDGE, DEFAULT_MAX_FPS, DEFAULT_MIN_CHANGE, HEARTBEAT_SECONDS,
    HEARTBEAT_TIMEOUT, MAX_FRAME_BYTES, PROTOCOL_VERSION, HelperFrame,
    HelperHello, HelperPreview, ShareAccepted, ShareCommand, ShareEnded,
)

class ScreenHub:
    def __init__(self, runtime):
        self.runtime = runtime
        self.devices: dict[str, dict] = {}
        self.pending_sockets: dict[str, set[WebSocket]] = {}
        self.limits = PairLimits()
        self.shares: dict[str, ShareBuffer] = {}
        self.walkthroughs = Takes(self)
        self.pending_codes: dict[str, tuple[int, float]] = {}
        self.snap_waiters: dict[str, tuple[ShareBuffer, asyncio.Future]] = {}
        self.preview_waiters: dict[str, tuple[str, str | int, asyncio.Future]] = {}
        self.elements = ElementsHub(self)
        self.window_grants = WindowGrants(self)
        self.control = ControlHub(self)
        self.tools = LocalTools(self)

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def issue_pair_code(self, owner_id: int, conv_id: str | None = None) -> str:
        code = secrets.token_hex(4).upper()
        self.pending_codes = {k: v for k, v in self.pending_codes.items() if v[1] > time.time()}
        while code in self.pending_codes:
            code = secrets.token_hex(4).upper()
        self.pending_codes[code] = (owner_id, time.time() + 300)
        return code

    def claim_pair_code(self, code: str, name: str, os_name: str) -> tuple[str, str, int, None] | None:
        row = self.pending_codes.pop(code.upper(), None)
        if not row or row[1] <= time.time():
            return None
        owner_id, _ = row
        device_id, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        self.runtime.db._exec(
            "INSERT INTO screen_devices(id,owner_id,conv_id,name,os,token_hash,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (device_id, owner_id, None, name[:120], os_name[:40], self.digest(token), time.time()),
        )
        return device_id, token, owner_id, None

    async def connect(self, ws: WebSocket, device: dict) -> None:
        ident = device["id"]
        self.pending_sockets.setdefault(ident, set()).add(ws)
        try:
            await ws.accept()
            first = await asyncio.wait_for(ws.receive_text(), HEARTBEAT_TIMEOUT)
            hello = HelperHello.model_validate_json(first)
            if hello.protocol != PROTOCOL_VERSION:
                await ws.close(code=4400, reason="unsupported helper protocol")
                return
            if not device_valid(self, ident):
                await ws.close(code=4403, reason="device revoked")
                return
            current = {**device, "socket": ws, "name": hello.device_name,
                       "os": hello.os, "helper_version": hello.helper_version, "control": hello.control,
                       "tools": hello.tools, "monitors": [item.model_dump() for item in hello.monitors],
                       "last_seen": time.monotonic()}
            old = self.devices.get(ident)
            if old:
                await old["socket"].close(code=4409, reason="reconnected")
                await self.window_grants.disconnected(ident)
                share = next((v for v in self.shares.values() if v.device_id == ident), None)
                if share:
                    await self.stop_share(share.share_id, "device reconnected")
            if not device_valid(self, ident):
                await ws.close(code=4403, reason="device revoked")
                return
            self.devices[ident] = current
            self.pending_sockets.get(ident, set()).discard(ws)
            await self._device_event(current, True)
            last_ping = time.monotonic()
            while True:
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    if time.monotonic() - current["last_seen"] >= HEARTBEAT_TIMEOUT:
                        break
                    await ws.send_json({"type": "ping"})
                    last_ping = time.monotonic()
                    continue
                current["last_seen"] = time.monotonic()
                if current["last_seen"] - last_ping >= HEARTBEAT_SECONDS:
                    await ws.send_json({"type": "ping"})
                    last_ping = current["last_seen"]
                message = json.loads(raw)
                kind = message.get("type")
                if kind == "ping":
                    await self.window_grants.expire()
                    await ws.send_json({"type": "pong"})
                    continue
                if kind == "pong":
                    continue
                if kind == "frame":
                    meta = HelperFrame.model_validate(message)
                    data = await asyncio.wait_for(ws.receive_bytes(), HEARTBEAT_TIMEOUT)
                    if len(data) > MAX_FRAME_BYTES:
                        await ws.send_json({"type": "error", "request_id": meta.request_id,
                                            "message": "frame exceeds 4 MB"})
                        continue
                    await self._frame(current, meta, data)
                elif kind == "preview":
                    meta = HelperPreview.model_validate(message)
                    data = await asyncio.wait_for(ws.receive_bytes(), HEARTBEAT_TIMEOUT)
                    if len(data) <= MAX_FRAME_BYTES:
                        entry = self.preview_waiters.get(meta.request_id)
                        if entry and entry[:2] == (ident, meta.monitor_id) and not entry[2].done():
                            entry[2].set_result({**meta.model_dump(), "data": data})
                elif kind == "share_accepted":
                    result = ShareAccepted.model_validate(message)
                    share = self._share(result.share_id, ident)
                    if share and share.status == "waiting":
                        share.status = "active"
                        bump_runtime(self.runtime)
                        await self._line_event(share.conv_id, self._share_view(share, current))
                elif kind in ("share_declined", "share_stopped"):
                    result = ShareEnded.model_validate(message)
                    share = self._share(result.share_id, ident)
                    if share:
                        await self.stop_share(share.share_id, result.reason)
                elif kind in WINDOW_MESSAGES:
                    await self.window_grants.from_helper(current, message)
                elif kind in ("window_elements", "window_element_result"):
                    self.elements.receive(current, message)
                elif kind in CONTROL_MESSAGES:
                    await self.control.from_helper(current, message)
                elif kind in TOOL_MESSAGES:
                    await self.tools.from_helper(current, message)
                elif kind == "error":
                    request_id = message.get("request_id")
                    entry = self.snap_waiters.get(request_id)
                    error = ValueError(str(message.get("message", "helper error")))
                    if entry and entry[0].device_id == ident and not entry[1].done():
                        entry[1].set_exception(error)
                    entry = self.preview_waiters.get(request_id)
                    if entry and entry[0] == ident and not entry[2].done():
                        entry[2].set_exception(error)
        except (WebSocketDisconnect, asyncio.CancelledError, TimeoutError,
                ValidationError, ValueError, KeyError, RuntimeError):
            pass
        finally:
            pending = self.pending_sockets.get(ident)
            if pending is not None:
                pending.discard(ws)
                if not pending:
                    self.pending_sockets.pop(ident, None)
            if self.devices.get(ident, {}).get("socket") is ws:
                self.devices.pop(ident, None)
                await self.window_grants.disconnected(ident)
                await self._device_event(device, False)
                await self.tools.end_device(ident, "the computer disconnected")
                share = next((item for item in self.shares.values() if item.device_id == ident), None)
                if share:
                    await self.stop_share(share.share_id, "device disconnected")

    def _share(self, share_id: str | None, device_id: str) -> ShareBuffer | None:
        return next((share for share in self.shares.values()
                     if share.share_id == share_id and share.device_id == device_id), None)

    async def _frame(self, device: dict, meta: HelperFrame, data: bytes) -> None:
        await add_frame(self, device, meta, data)

    async def start_share(self, conv_id: str, owner_id: int, requested_by: str,
                          device_id: str, region: dict, line_name: str,
                          walkthrough: bool = False, control: bool = False) -> ShareBuffer:
        device = self.devices.get(device_id)
        if not device or device["owner_id"] != owner_id:
            raise ValueError("choose one of your online computers")
        if conv_id in self.shares or any(item.device_id == device_id for item in self.shares.values()):
            raise ValueError("this line or computer already has an active share")
        if not any(region["x"] >= m["x"] and region["y"] >= m["y"]
                   and region["x"] + region["width"] <= m["x"] + m["width"]
                   and region["y"] + region["height"] <= m["y"] + m["height"]
                   for m in device["monitors"]):
            raise ValueError("region must fit inside a monitor")
        share = ShareBuffer(str(uuid.uuid4()), conv_id, device_id, owner_id, requested_by, region)
        self.shares[conv_id] = share
        if walkthrough:
            self.walkthroughs.create(share)
        command = ShareCommand(type="start_share", share_id=share.share_id, conv_id=conv_id,
                               line_name=line_name, requested_by=requested_by,
                               region=region, max_fps=DEFAULT_MAX_FPS,
                               long_edge=DEFAULT_LONG_EDGE, min_change=DEFAULT_MIN_CHANGE,
                               control=control and not walkthrough)
        try:
            await device["socket"].send_json(command.model_dump())
        except Exception:
            self.shares.pop(conv_id, None)
            self.walkthroughs.discard(share.share_id)
            raise
        if command.control:
            self.control.expect(share, requested_by)
        await self._line_event(conv_id, self._share_view(share, device))
        return share

    async def stop_share(self, share_id: str | None, reason: str = "stopped") -> None:
        share = next((item for item in self.shares.values() if item.share_id == share_id), None)
        if not share:
            return
        await stop_screen_share(self, share, reason)

    async def capture(self, conv_id: str) -> tuple[ShareBuffer, BufferedFrame]:
        return await capture(self, conv_id)

    async def preview(self, device_id: str, owner_id: int, monitor_id: str) -> dict:
        return await preview(self, device_id, owner_id, monitor_id)

    async def _line_event(self, conv_id: str, payload: dict) -> None:
        for ws in list(self.runtime.sockets.get(conv_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                pass

    async def _device_event(self, device: dict, online: bool) -> None:
        payload = {"type": "screen_devices_changed", "device_id": device["id"],
                   "online": online}
        for sockets in list(self.runtime.sockets.values()):
            for ws in list(sockets):
                if getattr(ws, "screen_owner_id", None) != device["owner_id"]:
                    continue
                try:
                    await ws.send_json(payload)
                except Exception:
                    pass

    def _share_view(self, share: ShareBuffer, device: dict) -> dict:
        take = self.walkthroughs.items.get(share.share_id)
        return {"type": "screen_share", "share": {
            "share_id": share.share_id, "handle": share.requested_by,
            "device_name": device["name"], "region": share.region,
            "status": share.status,
            "walkthrough": take is not None,
            "recording": bool(take and take.started is not None and not take.stopped),
            "control": self.control.view(share),
        }}
