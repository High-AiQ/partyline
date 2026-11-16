"""Named wire contracts for orchestrator roots and their task lines."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .goal import MAX_TASK_GOAL
from .task_modes import TaskMode


class CaptainStyleIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    captain_mode: Literal['orchestrator']
    default_review_policy: str = Field(default='captain', min_length=1, max_length=120)


class SuiteRepositoryIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    repository: str = Field(min_length=1, max_length=4096)
    batch: list[str] = Field(min_length=1, max_length=128)


class TaskIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120, pattern=r'\S')
    goal: str = Field(min_length=1, max_length=MAX_TASK_GOAL, pattern=r'\S')
    implementer: str = Field(min_length=1, max_length=120)
    review: str | None = Field(default=None, min_length=1, max_length=120)
    base: Literal['head', 'upstream'] = 'head'
    mode: TaskMode = Field(
        default='full',
        description='full (default): review as needed, with only affected tests. express: no review '
                    'and no tests, when a person says so or the captain decides. suite: every suite '
                    'on an ordered merged batch, no reviewer; deliver results, never push or open a PR. '
                    'Fixed at creation; legacy light is accepted as full.')
    repository: str | None = Field(default=None, min_length=1, max_length=4096)
    batch: list[str] = Field(default_factory=list, max_length=128,
                            description='Suite only: task line IDs/tags (accepted SHAs) and/or explicit '
                                        'commit SHAs, in cherry-pick order, in repository.')
    repositories: list[SuiteRepositoryIn] | None = Field(default=None, min_length=1, max_length=8)

    memory_limit: str | None = Field(default=None, pattern=r'^[1-9][0-9]{0,5}[KMG]$')
    write_set: list[str] = Field(
        default_factory=list, max_length=32,
        description='Absolute paths to pre-grant to the task line before its implementer starts, so it '
                    'never stalls to ask: the same validation and authority as approving a write-set '
                    'request (inside your own grants or checkout; a person decides anything wider).')

    @model_validator(mode='after')
    def suite_inputs(self):
        if self.repositories is not None:
            if {'repository', 'batch'} & self.model_fields_set:
                raise ValueError('pass repositories or repository and batch, not both')
            names = [item.repository for item in self.repositories]
            if len(set(names)) != len(names):
                raise ValueError('each repository may appear once')
        if self.mode == 'suite' and not (self.repositories or (self.repository and self.batch)):
            raise ValueError('suite tasks require repositories or repository and a non-empty ordered batch')
        if self.mode != 'suite' and (self.repositories or self.repository or self.batch):
            raise ValueError('repositories, repository and batch are for suite tasks')
        return self

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


class DeliverIn(BaseModel):
    """Text delivery; a suite run also records its integration tip from the workspace."""

    model_config = ConfigDict(extra='forbid')
    what: str = Field(min_length=1, max_length=1000)
    where: str = Field(min_length=1, max_length=500)
    repositories: list[RepositoryShaIn] | None = Field(default=None, min_length=1, max_length=8)

    @model_validator(mode='after')
    def unique_repositories(self):
        names = [item.repository for item in self.repositories or []]
        if len(set(names)) != len(names):
            raise ValueError('each repository may appear once')
        return self


class BlockedIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=1500, pattern=r'\S')


class WaitingIn(BaseModel):
    """A long wait the implementer or reviewer declares: what it waits for, and for how long."""

    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=1500, pattern=r'\S')
    seconds: int = Field(default=900, ge=60, le=3600)


class ResumeIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    note: str | None = Field(default=None, min_length=1, max_length=1500, pattern=r'\S')


class ReopenIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    goal: str = Field(min_length=1, max_length=MAX_TASK_GOAL, pattern=r'\S')


class SuiteReopenIn(ReopenIn):
    repository: str | None = Field(default=None, min_length=1, max_length=4096)
    batch: list[str] | None = Field(default=None, min_length=1, max_length=128)
    repositories: list[SuiteRepositoryIn] | None = Field(default=None, min_length=1, max_length=8)

    @model_validator(mode='after')
    def one_form(self):
        if self.repositories is not None:
            if {'repository', 'batch'} & self.model_fields_set:
                raise ValueError('pass repositories or repository and batch, not both')
            names = [item.repository for item in self.repositories]
            if len(set(names)) != len(names):
                raise ValueError('each repository may appear once')
        return self


class SuiteCommit(BaseModel):
    sha: str
    task: str | None = None


class SuiteRepository(BaseModel):
    repository: str
    batch: list[SuiteCommit]
    path: str | None = None


class VerdictIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    verdict: Literal['approve', 'changes']
    sha: str | None = Field(default=None, pattern=r'^[0-9a-f]{4,64}$')
    repositories: list[RepositoryShaIn] | None = Field(default=None, min_length=1, max_length=8)
    findings: str = Field(min_length=1, max_length=1500)
    # Explicit captain override of a staffed review; an ordinary call keeps the
    # reviewer-of-record authorization unchanged.
    override: bool = Field(
        default=False,
        description='Root captain only: explicitly override the staffed review, supersede the '
                    'reviewer and record this verdict as the captain.')


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
    mode: TaskMode = 'full'
    suite_repository: str | None = None
    suite_batch: list[SuiteCommit] = Field(default_factory=list)
    suite_repositories: list[SuiteRepository] = Field(default_factory=list)
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
    overridden_by: str | None = None
    goal: str = ''
    creation_error: str | None = None
    review_hold: str | None = None


class TaskStatus(BaseModel):
    """A task write's reply: the line's identity and state, never its prose.

    The goal, findings, previous findings, report body and workspace detail stay on the
    read tools (`tasks(conv_id)`, `goal`, `reports get`). `goal_chars` acknowledges a goal write.
    """

    conv_id: str
    root_id: str
    implementer_id: str
    reviewer_id: str | None = None
    tag: str | None = None
    implementer_handle: str | None = None
    reviewer_handle: str | None = None
    policy: str
    mode: TaskMode = 'full'
    suite_repository: str | None = None
    suite_batch: list[SuiteCommit] = Field(default_factory=list)
    suite_repositories: list[SuiteRepository] = Field(default_factory=list)
    status: Literal['implementing', 'idle', 'in_review', 'approved', 'done', 'blocked']
    round: int
    sha: str | None = None
    repositories: list[ReviewedRepository] = Field(default_factory=list)
    merged: bool
    report_id: int | None = None
    wait_until: float | None = None
    overridden_by: str | None = None
    creation_error: str | None = None
    goal_chars: int | None = None
    review_hold: str | None = None


class NudgeReviewerIn(BaseModel):
    model_config = ConfigDict(extra='forbid')


class MessageTaskIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=4000, pattern=r'\S')
    to: Literal['implementer', 'reviewer'] = 'implementer'
    hold_review: bool = Field(default=True, description='While the task is in review, hold approval '
                              'of its current SHA after messaging the implementer. Set false for '
                              'informational messages.')


class ReviewHoldIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    hold: bool


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


class EnvGapIn(BaseModel):
    repository: str = Field(min_length=1, max_length=4096)
    subpath: str = Field(default='.', max_length=1024)
    what_failed: str = Field(min_length=1, max_length=2000)
    tried: str = Field(min_length=1, max_length=2000)
