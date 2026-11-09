"""Bounded helper requests and cleanup for ephemeral screen shares."""

import asyncio
import uuid

from fastapi import WebSocketDisconnect

SNAP_TIMEOUT_SECONDS = 3
PREVIEW_TIMEOUT_SECONDS = 3


def active(hub, share) -> bool:
    return hub.shares.get(share.conv_id) is share and share.status == "active"


def end_share(hub, share) -> None:
    """Forget the share before yielding, and cancel its outstanding captures."""
    from .capability_versions import bump_runtime
    bump_runtime(hub.runtime)
    hub.shares.pop(share.conv_id, None)
    share.status = "stopped"
    share.frames.clear()
    share.attached.clear()
    for request_id, (owner, future) in list(hub.snap_waiters.items()):
        if owner is share:
            hub.snap_waiters.pop(request_id, None)
            future.cancel()


async def _await_frame(future):
    return await future


async def capture(hub, conv_id):
    share = hub.shares.get(conv_id)
    if not share or share.status != "active":
        raise ValueError("nobody is sharing a screen on this line")
    device = hub.devices.get(share.device_id)
    if not device:
        raise ValueError("the sharing computer is offline")
    request_id = str(uuid.uuid4())
    future = asyncio.get_running_loop().create_future()
    hub.snap_waiters[request_id] = (share, future)
    try:
        async with asyncio.timeout(SNAP_TIMEOUT_SECONDS):
            await device["socket"].send_json({"type": "snap", "share_id": share.share_id,
                                               "request_id": request_id})
            frame = await _await_frame(future)
        if not active(hub, share):
            raise ValueError("screen sharing has stopped")
        return share, frame
    except asyncio.CancelledError:
        if not asyncio.current_task().cancelling() and not active(hub, share):
            raise ValueError("screen sharing has stopped") from None
        raise
    except (TimeoutError, ValueError, OSError, RuntimeError, WebSocketDisconnect):
        if not active(hub, share):
            raise ValueError("screen sharing has stopped") from None
        if share.frames:
            return share, share.frames[-1]
        raise ValueError("the sharing computer did not provide a frame") from None
    finally:
        hub.snap_waiters.pop(request_id, None)
        if not future.done():
            future.cancel()
        elif not future.cancelled():
            future.exception()


async def preview(hub, device_id, owner_id, monitor_id):
    device = hub.devices.get(device_id)
    if not device or device["owner_id"] != owner_id:
        raise ValueError("computer is offline")
    matches = [m["id"] for m in device["monitors"] if str(m["id"]) == monitor_id]
    if len(matches) != 1:
        raise ValueError("monitor not found or ambiguous")
    actual_id = matches[0]
    request_id = str(uuid.uuid4())
    future = asyncio.get_running_loop().create_future()
    hub.preview_waiters[request_id] = (device_id, actual_id, future)
    try:
        async with asyncio.timeout(PREVIEW_TIMEOUT_SECONDS):
            await device["socket"].send_json({"type": "get_preview", "request_id": request_id,
                                               "monitor_id": actual_id, "long_edge": 640})
            return await future
    except TimeoutError:
        raise
    except (OSError, RuntimeError, WebSocketDisconnect) as exc:
        raise ValueError("computer disconnected during preview") from exc
    finally:
        hub.preview_waiters.pop(request_id, None)
        if not future.done():
            future.cancel()
        elif not future.cancelled():
            future.exception()
