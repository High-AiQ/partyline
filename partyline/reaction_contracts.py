"""Named contracts for emoji reactions."""

from typing import Literal

from pydantic import BaseModel


ReactionType = Literal["human", "agent"]


class ReactionResponse(BaseModel):
    emoji: str
    reactors: list[str]
    mine: bool = False


class ReactionRequest(BaseModel):
    emoji: str


class ReactionEvent(BaseModel):
    type: Literal["reaction"] = "reaction"
    message_id: int
    reactions: list[ReactionResponse]
