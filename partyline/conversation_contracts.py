"""Named contracts for conversation operations."""

from pydantic import BaseModel, Field


class SkippedPurge(BaseModel):
    id: str
    reason: str


class PurgeAllResponse(BaseModel):
    purged: list[str] = Field(default_factory=list)
    skipped: list[SkippedPurge] = Field(default_factory=list)


class RetirementBlocker(BaseModel):
    code: str
    message: str


class BlockedArchiveResponse(BaseModel):
    """A refused retirement: one summary line plus every blocker behind it."""

    detail: str
    blockers: list[RetirementBlocker] = Field(default_factory=list)
