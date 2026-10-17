"""WebSocket streaming for the live terminal view."""

import asyncio
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .adapters import Adapter
from .auth_guard import (
    WS_FORBIDDEN, WS_POLICY_VIOLATION, bearer_token, resolve_principal, websocket_principal,
)
from .contracts import TerminalGeometry
from .machine_scope import Capability, allows
from .terminal_viewers import TerminalViewer

if TYPE_CHECKING:
    from .runtime import ChatRuntime

# Quiet terminals must also lose access promptly after credential/role changes.
AUTH_CHECK_INTERVAL = 1.0


class TerminalAuthority:
    def __init__(self, runtime, ws: WebSocket, att_id: str, conv_id: str, adapter: Adapter):
        self.runtime, self.ws = runtime, ws
        self.att_id, self.conv_id, self.adapter = att_id, conv_id, adapter
        self.token = bearer_token(ws.headers, ws.query_params)
        self.closed = False

    async def require(self, capability: Capability) -> bool:
        principal = resolve_principal(self.runtime.db, self.token)
        att = self.runtime.db.get_attachment(self.att_id)
        if (not self.closed and principal is not None and att is not None
                and att["conv_id"] == self.conv_id
                and self.runtime.live.get(self.att_id) is self.adapter
                and allows(self.runtime.db, principal, self.conv_id, capability)):
            return True
        if not self.closed:
            self.closed = True
            code = WS_POLICY_VIOLATION if principal is None else WS_FORBIDDEN
            reason = "authentication required" if principal is None else "terminal access denied"
            await self.ws.close(code=code, reason=reason)
        return False


async def _send_terminal(ws: WebSocket, viewer: TerminalViewer, authority: TerminalAuthority) -> None:
    while await authority.require("read"):
        try:
            data = await asyncio.wait_for(viewer.queue.get(), AUTH_CHECK_INTERVAL)
        except TimeoutError:
            continue
        if data is None or not await authority.require("read"):
            return
        await ws.send_bytes(data)


async def _receive_terminal(ws: WebSocket, adapter: Adapter, authority: TerminalAuthority) -> None:
    while True:
        data = await ws.receive_text()
        # Read-only viewers close on input, matching the REST keys policy.
        if not await authority.require("attach"):
            return
        adapter.write_terminal(data.encode("utf-8"))


def terminal_endpoint(runtime: "ChatRuntime"):
    async def stream(ws: WebSocket, att_id: str) -> None:
        if await websocket_principal(runtime.db, ws) is None:
            return
        adapter = runtime.live.get(att_id)
        att = runtime.db.get_attachment(att_id)
        await ws.accept()
        if adapter is None or att is None:
            await ws.close(code=4404, reason="attachment is not live")
            return
        authority = TerminalAuthority(runtime, ws, att_id, att["conv_id"], adapter)
        if not await authority.require("read"):
            return
        viewer = adapter.attach_terminal_viewer()
        tasks = []
        try:
            cols, rows = adapter.terminal_dimensions()
            if not await authority.require("read"):
                return
            await ws.send_text(TerminalGeometry(cols=cols, rows=rows).model_dump_json())
            if not await authority.require("read"):
                return
            await ws.send_text(viewer.snapshot)
            tasks = [asyncio.create_task(_send_terminal(ws, viewer, authority)),
                     asyncio.create_task(_receive_terminal(ws, adapter, authority))]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except WebSocketDisconnect:
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            adapter.detach_terminal_viewer(viewer)

    return stream


def register_terminal_route(app: FastAPI, runtime: "ChatRuntime") -> None:
    app.add_api_websocket_route(
        "/ws/attachments/{att_id}/terminal", terminal_endpoint(runtime)
    )
