"""Named wire contracts for attached processes and their working trees."""

from typing import Literal

from pydantic import BaseModel, Field


class CwdGitState(BaseModel):
    """Git identity observed from an attachment's exact working directory."""

    sha: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    dirty: bool


class BridgeRef(BaseModel):
    """The open line bridge this process is the ambassador of."""

    bridge_id: str
    peer_name: str
    peer_attachment_id: str
    peer_conv_id: str
    peer_conv_name: str


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
    memory_raw_bytes: int | None = Field(default=None, ge=0)
    memory_anon_bytes: int | None = Field(default=None, ge=0)
    memory_file_bytes: int | None = Field(default=None, ge=0)
    memory_kernel_bytes: int | None = Field(default=None, ge=0)
    memory_cap_bytes: int | None = Field(default=None, gt=0)
    memory_percent: int | None = Field(default=None, ge=0, le=100)
    bridge: BridgeRef | None = None
