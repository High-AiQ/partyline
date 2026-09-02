"""Closed wire contracts for immutable structured review decisions."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    presentation_message_id: int = Field(gt=0, strict=True)
    decision: Literal["approve", "reject"]


class ReviewObservation(BaseModel):
    """The exact Storytime review-observation row; do not add fields."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    presentation_message_id: str
    evidence_kind: Literal["decision"]
    evidence_ref: str
    sender_id: str
    decision: Literal["approve", "reject"]
    observed_at: datetime


class ReviewObservationPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observations: list[ReviewObservation]
