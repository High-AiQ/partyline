"""Contracts for line-wide process state and bulk controls."""

from typing import Literal

from pydantic import BaseModel, Field


class CloseProcessesResponse(BaseModel):
    ok: bool
    stopped: list[str]


class LineLiveEvent(BaseModel):
    type: Literal["line_live"] = "line_live"
    conversation_id: str
    live_count: int = Field(ge=0)
