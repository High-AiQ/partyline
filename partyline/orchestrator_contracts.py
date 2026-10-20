"""Named wire contracts for orchestrator roots and their task lines."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CaptainStyleIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    captain_mode: Literal['manager_tree', 'orchestrator']
    default_review_policy: str = Field(default='captain', min_length=1, max_length=120)


class TaskIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=3000)
    implementer: str = Field(min_length=1, max_length=120)
    review: str | None = Field(default=None, min_length=1, max_length=120)


class ReviewRequestIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sha: str | None = Field(default=None, pattern=r'^[0-9a-f]{4,64}$')
    what: str = Field(min_length=1, max_length=1000)
    where: str = Field(min_length=1, max_length=500)


class BlockedIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=1500, pattern=r'\S')


class VerdictIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    verdict: Literal['approve', 'changes']
    findings: str = Field(min_length=1, max_length=1500)


class TaskReview(BaseModel):
    conv_id: str
    root_id: str
    implementer_id: str
    implementer_preset: str
    policy: str
    reviewer_id: str | None = None
    status: Literal['implementing', 'in_review', 'approved', 'done', 'blocked']
    round: int
    sha: str | None = None
    review_worktree: str | None = None
    what: str
    location: str
    findings: str
    report_id: int | None = None
    merged: bool
    created_at: float
    reviewer_restarts: int = 0


class AutoCleanIn(BaseModel):
    enabled: bool = False
