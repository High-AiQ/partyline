"""Named wire contracts for orchestrator roots and their task lines."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    base: Literal['head', 'upstream'] = 'head'


class RepositoryShaIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    repository: str = Field(min_length=1, max_length=4096)
    sha: str = Field(pattern=r'^[0-9a-f]{4,64}$')


class ReviewedRepository(BaseModel):
    repository: str
    sha: str
    path: str


class ReviewRequestIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sha: str | None = Field(default=None, pattern=r'^[0-9a-f]{4,64}$')
    repositories: list[RepositoryShaIn] | None = Field(default=None, min_length=1, max_length=8)
    what: str = Field(min_length=1, max_length=1000)
    where: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def one_way_to_name_commits(self):
        if self.sha and self.repositories:
            raise ValueError('pass sha or repositories, not both')
        names = [item.repository for item in self.repositories or []]
        if len(set(names)) != len(names):
            raise ValueError('each repository may appear once')
        return self


class BlockedIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=1500, pattern=r'\S')


class WaitingIn(BaseModel):
    """A long wait the implementer declares: what it waits for, and for how long."""

    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=1500, pattern=r'\S')
    seconds: int = Field(default=900, ge=60, le=3600)


class ResumeIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    note: str | None = Field(default=None, min_length=1, max_length=1500, pattern=r'\S')


class ReopenIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    goal: str = Field(min_length=1, max_length=3000, pattern=r'\S')


class VerdictIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    verdict: Literal['approve', 'changes']
    findings: str = Field(min_length=1, max_length=1500)


class WorkspaceVisibility(BaseModel):
    repository: str
    path: str
    branch: str
    mirror_tip: str | None = None
    host_tip: str | None = None
    accepted_sha: str | None = None
    unaccepted_count: int = Field(default=0, ge=0)
    unaccepted_subjects: list[str] = Field(default_factory=list, max_length=5)


class TaskReview(BaseModel):
    conv_id: str
    root_id: str
    implementer_id: str
    implementer_preset: str
    policy: str
    reviewer_id: str | None = None
    status: Literal['implementing', 'idle', 'in_review', 'approved', 'done', 'blocked']
    round: int
    sha: str | None = None
    review_worktree: str | None = None
    repositories: list[ReviewedRepository] = Field(default_factory=list)
    workspaces: list[WorkspaceVisibility] = Field(default_factory=list)
    what: str
    location: str
    findings: str
    previous_findings: str = ''
    wait_reason: str = ''
    wait_until: float | None = None
    report_id: int | None = None
    merged: bool
    created_at: float
    reviewer_restarts: int = 0
    tag: str | None = None
    implementer_handle: str | None = None
    reviewer_handle: str | None = None


class MessageTaskIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=4000, pattern=r'\S')
    to: Literal['implementer', 'reviewer'] = 'implementer'


class ShareRefIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ref_or_sha: str = Field(max_length=2000)
    name: str = Field(min_length=1, max_length=64)
    repository: str | None = Field(default=None, min_length=1, max_length=4096)
    replace: bool = False


class ShareRefOut(BaseModel):
    sha: str
    ref: str
    example: str
    repository: str


class AutoCleanIn(BaseModel):
    enabled: bool = False
