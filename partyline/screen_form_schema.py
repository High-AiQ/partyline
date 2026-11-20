"""Input contract for independent assignments in one ordinary form-fill call."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Assignment(BaseModel):
    """One independent field assignment in a compact form-fill group."""
    model_config = ConfigDict(extra="forbid")
    element_id: str = Field(min_length=1, max_length=128)
    value: str = Field(max_length=500)
    action: Literal["set_value", "select"] = "set_value"
