"""Request safe window discovery or attachment from the paired helper."""
import asyncio
import uuid

from fastapi import HTTPException

from .op_timing import pushed
from .screen_protocol import WindowAccessChanged


async def update_mirror(hub, device, message):
    state = WindowAccessChanged.model_validate(message)
    hub.runtime.db._exec("INSERT INTO screen_device_window_access(device_id,enabled) VALUES(?,?) "
                         "ON CONFLICT(device_id) DO UPDATE SET enabled=excluded.enabled",
                         (device["id"], int(state.enabled)))
    device["window_access_enabled"] = state.enabled
    from .capability_versions import bump_runtime
    bump_runtime(hub.runtime)
    if not state.enabled:
        from .screen_audit import reset_window_access_notices
        reset_window_access_notices(hub.runtime, device["id"])
        await hub.window_grants.revoke_standing(device["id"])
    await hub._device_event(device, device["id"] in hub.devices)


class StandingWindows:
    def __init__(self, hub):
        self.hub = hub
        self.waiters = {}

    async def request(self, device, kind, **fields):
        if not device.get("window_access_enabled"):
            raise HTTPException(403, "window access is off in the helper")
        ident = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.waiters[ident] = (device["id"], future)
        try:
            await pushed("screen", device["socket"].send_json(
                {"type": kind, "request_id": ident, **fields}))
            return await asyncio.wait_for(future, 45)
        except (TimeoutError, OSError, RuntimeError) as exc:
            raise HTTPException(503, "the paired helper did not answer") from exc
        finally:
            self.waiters.pop(ident, None)

    def receive(self, device, message):
        waiter = self.waiters.get(message.get("request_id"))
        if waiter and waiter[0] == device["id"] and not waiter[1].done():
            waiter[1].set_result(message)
