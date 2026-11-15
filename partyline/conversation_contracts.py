"""Named contracts for conversation operations."""

from typing import Literal

import json

from pydantic import BaseModel, Field, field_validator

from .task_modes import TaskMode


class SkippedPurge(BaseModel):
    id: str
    reason: str


class PurgeAllResponse(BaseModel):
    purged: list[str] = Field(default_factory=list)
    skipped: list[SkippedPurge] = Field(default_factory=list)


class ConversationStarResponse(BaseModel):
    ok: bool
    starred: bool


class RetirementBlocker(BaseModel):
    code: str
    message: str


class BlockedArchiveResponse(BaseModel):
    """A refused retirement: one summary line plus every blocker behind it."""

    detail: str
    blockers: list[RetirementBlocker] = Field(default_factory=list)
    required_flags: list[str] = Field(default_factory=list)


class ConversationResponse(BaseModel):
    captain_mode: Literal["orchestrator"] = "orchestrator"
    default_review_policy: str = "captain"
    task_status: Literal["implementing", "idle", "in_review", "approved", "done", "blocked"] | None = None
    task_round: int | None = None
    task_mode: TaskMode | None = None
    task_root_name: str | None = None
    task_implementer_name: str | None = None
    task_reviewer_name: str | None = None
    task_repositories: list[str] = Field(default_factory=list)

    @field_validator('task_repositories', mode='before')
    @classmethod
    def _reviewed(cls, value):
        """The task row stores JSON; the rail and header show ``repository@sha``."""
        if isinstance(value, str):
            value = json.loads(value or '[]')
        return [f"{item['repository']}@{item['sha'][:12]}" if isinstance(item, dict) else item
                for item in value or []]
    id: str
    name: str
    created_at: float
    topic: str = ""
    goal: str = ""
    cwd: str | None = None
    archived_at: float | None = None
    live_count: int = Field(default=0, ge=0)
    parent_id: str | None = None
    chapter_of: str | None = None
    chapter: int = Field(default=1, ge=1)
    starred: bool = False


class LineStatus(BaseModel):
    """A line write's reply: where the line is and how long its goal is, never the goal or topic.

    The goal and topic are read on the line's conversation record (``GET /api/conversations/{id}``).
    """

    id: str
    name: str
    parent_id: str | None = None
    cwd: str | None = None
    goal_chars: int = Field(default=0, ge=0)

    @classmethod
    def of(cls, conv: dict) -> "LineStatus":
        return cls(id=conv["id"], name=conv["name"], parent_id=conv.get("parent_id"),
                   cwd=conv.get("cwd"), goal_chars=len(conv.get("goal") or ""))
