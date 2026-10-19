"""Named contracts for conversation operations."""

from typing import Literal

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


class ConversationResponse(BaseModel):
    captain_mode: Literal["manager_tree", "orchestrator"] = "manager_tree"
    default_review_policy: str = "captain"
    task_status: Literal["implementing", "in_review", "approved", "done", "blocked"] | None = None
    task_round: int | None = None
    task_root_name: str | None = None
    task_implementer_name: str | None = None
    task_reviewer_name: str | None = None
    id: str
    name: str
    created_at: float
    topic: str = ""
    goal: str = ""
    cwd: str | None = None
    archived_at: float | None = None
    live_count: int = Field(default=0, ge=0)
    parent_id: str | None = None
