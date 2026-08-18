"""Wire contracts for a line's shared task board."""

from typing import Literal

from pydantic import BaseModel, Field

MAX_TASK_BODY = 500
MAX_TASK_OWNER = 100


class Task(BaseModel):
    id: int
    conv_id: str
    body: str
    status: Literal["open", "done"] = "open"
    owner: str | None = None
    created_at: float
    updated_at: float


class TaskCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_TASK_BODY)
    owner: str | None = Field(default=None, max_length=MAX_TASK_OWNER)


class TaskUpdateRequest(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=MAX_TASK_BODY)
    status: Literal["open", "done"] | None = None
    owner: str | None = Field(default=None, max_length=MAX_TASK_OWNER)
