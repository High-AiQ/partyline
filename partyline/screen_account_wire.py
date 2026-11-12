"""The ordinary chat wire's account view, used while no line is open."""

from fastapi import WebSocketDisconnect
from starlette.websockets import WebSocketState

from .browser_snapshots import hello_payload
from .screen_snapshot import send_snapshot
from .op_timing import pushed

ACCOUNT_WIRE = "~account"


async def serve_account_wire(runtime, ws, handle, build, version, instance):
    await ws.accept()
    runtime.sockets.setdefault(ACCOUNT_WIRE, set()).add(ws)
    try:
        while True:
            message = await ws.receive_json()
            if isinstance(message, dict) and message.get("type") == "hello":
                await pushed("screen", ws.send_json(await hello_payload(
                    runtime, ACCOUNT_WIRE, handle, build, version, instance)))
                await send_snapshot(runtime, ws, ACCOUNT_WIRE)
    except WebSocketDisconnect:
        pass
    finally:
        runtime.sockets.get(ACCOUNT_WIRE, set()).discard(ws)


async def serve_wire(runtime, ws, conv_id, handle, frontend_build, server_version,
                     instance_name=None, reattacher=None):
    try:
        if conv_id == ACCOUNT_WIRE:
            await serve_account_wire(runtime, ws, handle, frontend_build, server_version,
                                     instance_name)
        else:
            await runtime.websocket(ws, conv_id, handle, frontend_build, server_version,
                                    instance_name, reattacher)
    except RuntimeError:
        # Shutdown, or a reconnect that superseded this socket, closed it while a reply
        # was being prepared. Sending to a closed socket is a disconnect, not a fault.
        if ws.application_state is not WebSocketState.DISCONNECTED:
            raise
