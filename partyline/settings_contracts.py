"""Contracts for instance-wide settings."""

from pydantic import BaseModel, Field


class GlobalProseIn(BaseModel):
    value: str | None = Field(max_length=10000)


class GlobalProseResponse(BaseModel):
    value: str | None
