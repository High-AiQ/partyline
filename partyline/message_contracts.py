"""Named contracts for bounded human message history."""

from pydantic import BaseModel

from .contracts import (
    AttachmentResponse,
    ConversationResponse,
    MessageResponse,
)
from .presence_contracts import PresenceState


class ConversationDetailResponse(BaseModel):
    conversation: ConversationResponse
    messages: list[MessageResponse]
    has_more_messages: bool = False
    attachments: list[AttachmentResponse]
    # Which attachments are mid-turn right now. A tab that opens or reconnects
    # during someone's turn would otherwise show nothing until the next
    # transition — the indicator would be blank exactly when it matters.
    working: list[str] = []
    # Idle tombstones keep buffered pre-snapshot events from relighting a badge.
    presence: list[PresenceState] | None = None


class MessagePageResponse(BaseModel):
    messages: list[MessageResponse]
    has_more: bool
