"""Route read-only window snapshots to the locally consented helper."""
import asyncio
import json
import uuid

from fastapi import APIRouter, Request

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .screen_element_actions import ElementAction, element_action
from .screen_device_access import line_devices


class ElementsHub:
    def __init__(self, hub):
        self.hub = hub
        self.waiters = {}

    async def read(self, conv_id, device_name=None):
        devices = line_devices(self.hub, conv_id, device_name)
        if not devices:
            return {"elements_unavailable": "no paired computer online"}
        if len(devices) != 1:
            return {"elements_unavailable": "multiple computers online; specify a device"}
        device = devices[0]
        ident = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.waiters[ident] = (device["id"], future)
        try:
            async with asyncio.timeout(35):
                await device["socket"].send_json({"type": "read_window_elements", "request_id": ident})
                response = await future
            if response.get("elements_unavailable"):
                return {"elements_unavailable": str(response["elements_unavailable"])[:160],
                        **({"truncated": True} if response.get("truncated") else {})}
            lines = [json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                     for item in response.get("elements", [])]
            return {"snapshot_id": response.get("snapshot_id"), "window_title": response.get("window_title"),
                    "process_name": response.get("process_name"),
                    "truncated": bool(response.get("truncated")),
                    **({"truncation": str(response["truncation"])[:300]}
                       if response.get("truncation") else {}),
                    "elements": "\n".join(lines)}
        except (TimeoutError, OSError, RuntimeError):
            return {"elements_unavailable": "helper did not respond"}
        finally:
            self.waiters.pop(ident, None)
            if not future.done():
                future.cancel()

    def receive(self, device, message):
        entry = self.waiters.get(message.get("request_id"))
        if entry and entry[0] == device["id"] and not entry[1].done():
            entry[1].set_result(message)


def elements_router(runtime, hub):
    router = APIRouter()

    @router.post("/api/conversations/{conv_id}/screen-elements")
    async def elements(conv_id: str, request: Request, device: str | None = None):
        deny_unless(runtime.db, request_principal(request), conv_id, "read")
        return await hub.elements.read(conv_id, device)

    @router.post("/api/conversations/{conv_id}/screen-control/element-action")
    async def act(conv_id: str, body: ElementAction, request: Request):
        return await element_action(runtime, hub, conv_id, body, request)

    return router
