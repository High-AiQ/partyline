"""Contracts for the read-only process overview of a line and its descendants."""

from typing import Literal

from pydantic import BaseModel, Field


class ProcessOverviewAttachment(BaseModel):
    """One live attachment on a line, as the reclaim caller sees it."""

    id: str
    handle: str
    adapter: str
    pid: int | None = None
    phase: Literal["working", "speaking", "idle"] = "idle"
    # Best-effort Linux VmRSS; None when unknown (dead pid, no /proc, non-Linux).
    rss_bytes: int | None = Field(default=None, ge=0)
    runtime_started_at: float | None = None


class ProcessOverviewLine(BaseModel):
    id: str
    name: str
    goal_set: bool = False
    accepted_sha: str | None = None
    attachments: list[ProcessOverviewAttachment] = Field(default_factory=list)


class ProcessOverviewResponse(BaseModel):
    lines: list[ProcessOverviewLine] = Field(default_factory=list)
