"""Validate helper Chrome state before including it in owner device snapshots."""
from typing import Literal

from pydantic import BaseModel, Field


class ChromeState(BaseModel):
    state: Literal["not_enabled", "awaiting_approval", "connected", "refused"]
    detail: str = Field(default="", max_length=300)


async def receive(hub, device, message):
    device["chrome"] = ChromeState.model_validate(message).model_dump()
    await hub._device_event(device, True)
