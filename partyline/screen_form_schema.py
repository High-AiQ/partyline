"""Input contract for independent assignments in one ordinary form-fill call."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Condition(BaseModel):
    """A freshly matched control that must be enabled (and have the requested option) before input."""
    model_config = ConfigDict(extra="forbid")
    root: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    control_type: str | None = Field(default=None, min_length=1, max_length=40)
    timeout_ms: int = Field(default=2000, ge=0, le=10_000, strict=True)


class Assignment(BaseModel):
    """One independent field assignment in a compact form-fill group."""
    model_config = ConfigDict(extra="forbid")
    element_id: str = Field(min_length=1, max_length=128)
    value: str = Field(max_length=500)
    action: Literal["set_value", "select"] = "set_value"
    when: Condition | None = None
