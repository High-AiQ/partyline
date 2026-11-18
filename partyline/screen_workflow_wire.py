"""Cancel a workflow helper request without revoking the underlying window grant."""

import asyncio
from contextlib import asynccontextmanager

from starlette.websockets import WebSocketDisconnect

from .op_timing import pushed


@asynccontextmanager
async def operation(device, ident, grant_id, dispatch):
    if dispatch:
        dispatch(ident)
    try:
        yield
    except (asyncio.CancelledError, TimeoutError):
        if dispatch:
            try:
                async with asyncio.timeout(2):
                    payload = {"type": "cancel_workflow_action", "request_id": ident, "grant_id": grant_id}
                    await pushed("screen", device["socket"].send_json(payload))
            except (TimeoutError, OSError, RuntimeError, WebSocketDisconnect):
                pass  # an action already sent remains unconfirmed
        raise
