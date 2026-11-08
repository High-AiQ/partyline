"""Route snapshots to one window explicitly granted to the calling attachment."""
import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException, Request

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .screen_grants import require_window, resolve_window
from .screen_element_actions import ElementAction, element_action


class ElementsHub:
    def __init__(self, hub):
        self.hub = hub
        self.waiters = {}

    async def exchange(self, principal, grant, device, kind, **fields):
        require_window(self.hub, principal, grant["id"])
        ident = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.waiters[ident] = (device["id"], future)
        try:
            async with asyncio.timeout(35):
                await device["socket"].send_json({"type": kind, "request_id": ident,
                                                 "grant_id": grant["id"], **fields})
                response = await future
            try:
                require_window(self.hub, principal, grant["id"])
            except HTTPException:
                if kind == "read_window_elements":
                    raise
                status = response.get("status", "unknown")
                note = ("The action was performed; the grant has since ended." if status == "completed" else
                        "The grant has since ended; the action outcome is " + status +
                        ". Do not retry automatically.")
                return {"status": status, "grant_ended": True, "note": note}
            return response
        finally:
            self.waiters.pop(ident, None)
            if not future.done():
                future.cancel()

    async def read(self, principal, device_name=None, window=None):
        grant, device = resolve_window(self.hub, principal, window, device_name)
        try:
            response = await self.exchange(principal, grant, device, "read_window_elements")
            if response.get("elements_unavailable"):
                return {"elements_unavailable": str(response["elements_unavailable"])[:160],
                        **({"truncated": True} if response.get("truncated") else {})}
            lines = [json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                     for item in response.get("elements", [])]
            return {"window": grant["id"], "snapshot_id": response.get("snapshot_id"),
                    "window_title": grant["title"], "process_name": grant["process"],
                    "truncated": bool(response.get("truncated")),
                    **({"truncation": str(response["truncation"])[:300]}
                       if response.get("truncation") else {}),
                    "elements": "\n".join(lines)}
        except (TimeoutError, OSError, RuntimeError):
            return {"elements_unavailable": "helper did not respond"}

    def receive(self, device, message):
        entry = self.waiters.get(message.get("request_id"))
        if entry and entry[0] == device["id"] and not entry[1].done():
            entry[1].set_result(message)


def elements_router(runtime, hub):
    router = APIRouter()

    @router.post("/api/conversations/{conv_id}/screen-elements")
    async def elements(conv_id: str, request: Request, device: str | None = None, window: str | None = None):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "read")
        return await hub.elements.read(principal, device, window)

    @router.post("/api/conversations/{conv_id}/screen-control/element-action")
    async def act(conv_id: str, body: ElementAction, request: Request):
        return await element_action(runtime, hub, conv_id, body, request)

    return router
