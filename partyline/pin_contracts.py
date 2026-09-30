"""Contracts for per-line message pins."""

from pydantic import BaseModel, Field
from typing import Literal


class PinAliasIn(BaseModel):
    alias: str | None = Field(default=None, max_length=120)


class PinCreateIn(BaseModel):
    message_id: int = Field(ge=1)


class PinResponse(BaseModel):
    conversation_id: str
    message_id: int
    alias: str | None = None
    created_at: float
    message_available: bool
    message_text: str | None = None


class PinsChangedEvent(BaseModel):
    type: Literal["pins_changed"] = "pins_changed"
    conversation_id: str
    pins: list[PinResponse]
