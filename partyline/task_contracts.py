"""Wire contracts for a line's shared task board."""

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field

MAX_TASK_BODY = 500
MAX_TASK_OWNER = 100

# The board stores two statuses, but the words people reach for are wider than
# that. The digest line says "open tasks", the rows carry `"status": "open"`,
# and the obvious opposite of open is "completed" or "closed" — each of which
# used to come back as a bare 422 naming no valid value, so the write looked
# like it had landed unless the caller checked the response code. Every
# process adopting the board hit this in turn.
#
# Accepting the synonyms is the forgiving half; `TaskStatus` normalizes them
# to the two the store actually knows, so nothing downstream has to care.
STATUS_ALIASES = {
    "completed": "done",
    "complete": "done",
    "closed": "done",
    "finished": "done",
    "reopened": "open",
    "todo": "open",
}


def normalize_status(value):
    """Map a synonym onto a stored status, leaving anything else alone.

    An unknown word is passed through untouched so the `Literal` still
    rejects it — this widens what is understood, not what is accepted.
    """
    if isinstance(value, str):
        return STATUS_ALIASES.get(value.strip().lower(), value.strip().lower())
    return value


TaskStatus = Annotated[Literal["open", "done"], BeforeValidator(normalize_status)]


class Task(BaseModel):
    id: int
    conv_id: str
    body: str
    status: TaskStatus = "open"
    owner: str | None = None
    created_at: float
    updated_at: float


class TaskCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_TASK_BODY)
    owner: str | None = Field(default=None, max_length=MAX_TASK_OWNER)


class TaskUpdateRequest(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=MAX_TASK_BODY)
    status: TaskStatus | None = None
    owner: str | None = Field(default=None, max_length=MAX_TASK_OWNER)
