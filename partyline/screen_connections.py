"""Helper revocation and explicit delivery of share notices."""

from fastapi import WebSocketDisconnect


async def notice(hub, conv_id: str, text: str) -> None:
    message = await hub.runtime.post_message(conv_id, "system", "system", text)
    await hub.runtime.route_mentions(conv_id, message, force=True)


async def revoke(hub, device_id: str) -> None:
    device = hub.devices.pop(device_id, None)
    pending = list(hub.pending_sockets.pop(device_id, ()))
    if device:
        await hub._device_event(device, False)
        pending.append(device["socket"])
    for ws in pending:
        try:
            await ws.close(code=4403, reason="device revoked")
        except (RuntimeError, WebSocketDisconnect, OSError):
            pass
    await hub.window_grants.disconnected(device_id)
    await hub.tools.end_device(device_id, "computer revoked")
    share = next((s for s in hub.shares.values() if s.device_id == device_id), None)
    if share:
        await hub.stop_share(share.share_id, "computer revoked")
    for take in list(hub.walkthroughs.items.values()):
        if take.device_id == device_id:
            hub.walkthroughs.discard(take.share_id)



def device_valid(hub, device_id: str) -> bool:
    return hub.runtime.db._exec(
        "SELECT 1 FROM screen_devices WHERE id=? AND revoked_at IS NULL", (device_id,)
    ).fetchone() is not None
