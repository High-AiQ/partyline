"""WebSocket streaming for the live terminal view."""

import asyncio
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .adapters import Adapter
from .auth_guard import websocket_principal
from .contracts import TerminalGeometry
from .terminal_viewers import TerminalViewer

if TYPE_CHECKING:
    from .runtime import ChatRuntime


async def _send_terminal(ws: WebSocket, viewer: TerminalViewer) -> None:
    while True:
        data = await viewer.queue.get()
        if data is None:
            return
        await ws.send_bytes(data)


async def _receive_terminal(ws: WebSocket, adapter: Adapter) -> None:
    while True:
        adapter.write_terminal((await ws.receive_text()).encode("utf-8"))


def terminal_endpoint(runtime: "ChatRuntime"):
    async def stream(ws: WebSocket, att_id: str) -> None:
        # A terminal socket can type into a real pty, so it is gated exactly
        # like the chat socket: a valid credential or a 4401 close.
        if await websocket_principal(runtime.db, ws) is None:
            return
        adapter = runtime.live.get(att_id)
        await ws.accept()
        if adapter is None:
            await ws.close(code=4404, reason="attachment is not live")
            return
        viewer = adapter.attach_terminal_viewer()
        try:
            cols, rows = adapter.terminal_dimensions()
            await ws.send_text(TerminalGeometry(cols=cols, rows=rows).model_dump_json())
            await ws.send_text(viewer.snapshot)
            sending = asyncio.create_task(_send_terminal(ws, viewer))
            receiving = asyncio.create_task(_receive_terminal(ws, adapter))
            done, pending = await asyncio.wait(
                (sending, receiving), return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*done, return_exceptions=True)
            await asyncio.gather(*pending, return_exceptions=True)
        except WebSocketDisconnect:
            pass
        finally:
            adapter.detach_terminal_viewer(viewer)

    return stream


def register_terminal_route(app: FastAPI, runtime: "ChatRuntime") -> None:
    app.add_api_websocket_route(
        "/ws/attachments/{att_id}/terminal", terminal_endpoint(runtime)
    )
