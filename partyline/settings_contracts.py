"""Contracts for instance-wide settings."""

from pydantic import BaseModel, Field


class GlobalProseIn(BaseModel):
    value: str | None = Field(max_length=10000)


class GlobalProseResponse(BaseModel):
    value: str | None


class MaxCompactionsIn(BaseModel):
    """0 turns rotation off; the ceiling keeps a typo from meaning 'never'."""

    value: int = Field(ge=0, le=20)
