"""Validate helper Chrome state before including it in owner device snapshots."""
from typing import Literal

from pydantic import BaseModel, Field


class ChromeState(BaseModel):
    state: Literal["not_enabled", "awaiting_approval", "connected", "disconnected", "refused"]
    detail: str = Field(default="", max_length=300)
    transport: Literal["extension", "remote_debugging"] | None = None


async def receive(hub, device, message):
    if message.get("type") == "chrome_approval":  # which grants wait on the Allow prompt, not the tray state
        return await hub.window_grants.approvals.receive(device, message)
    device["chrome"] = ChromeState.model_validate(message).model_dump()
    await hub._device_event(device, True)
