"""Named contracts for conversation operations."""

from pydantic import BaseModel, Field


class SkippedPurge(BaseModel):
    id: str
    reason: str


class PurgeAllResponse(BaseModel):
    purged: list[str] = Field(default_factory=list)
    skipped: list[SkippedPurge] = Field(default_factory=list)
