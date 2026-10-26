"""Public read-only resource view shared by list and process overview."""

from typing import Literal

from pydantic import BaseModel, Field


class ResourceClaim(BaseModel):
    attachment_id: str
    handle: str
    holder_line: str
    note: str
    created_at: float
    granted_at: float | None = None


class LineResource(BaseModel):
    name: str
    capacity: int = 1
    holder: ResourceClaim | None = None
    queue: list[ResourceClaim] = Field(default_factory=list)


class ResourceList(BaseModel):
    resources: list[LineResource] = Field(default_factory=list)


class AcquireResult(BaseModel):
    status: Literal['held', 'queued']
    position: int
    holder: ResourceClaim | None = None
