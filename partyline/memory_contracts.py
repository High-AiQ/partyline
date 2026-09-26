"""Memory controls and host-observed exit evidence."""

from typing import Literal

from pydantic import BaseModel, Field


class ProcessExit(BaseModel):
    code: int
    reason: Literal["oom", "unverified", "exit"] = "exit"
    limit_bytes: int = Field(gt=0)
    peak_bytes: int | None = Field(default=None, ge=0)
    scope: str | None = None
    result: str | None = None


class MemoryIncident(ProcessExit):
    id: int
    created_at: float


class MemoryLimitRequest(BaseModel):
    limit: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,5}[KMG]$")


class MemorySettings(BaseModel):
    configured_limit: str | None = None
    effective_limit: str
    maximum_bytes: int
    last_incident: MemoryIncident | None = None
