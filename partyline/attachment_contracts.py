"""Named wire contracts for attached processes and their working trees."""

from typing import Literal

from pydantic import BaseModel, Field


class CwdGitState(BaseModel):
    """Git identity observed from an attachment's exact working directory."""

    sha: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    dirty: bool


class AttachmentResponse(BaseModel):
    id: str
    conv_id: str
    name: str
    adapter: str
    command: list[str]
    cwd: str
    status: Literal["starting", "running", "exited", "detached"]
    last_seen: int
    created_at: float
    cli_session: str | None = None
    cwd_git: CwdGitState | None = None
    memory_usage_bytes: int | None = Field(default=None, ge=0)
    memory_cap_bytes: int | None = Field(default=None, gt=0)
    memory_percent: int | None = Field(default=None, ge=0, le=100)
