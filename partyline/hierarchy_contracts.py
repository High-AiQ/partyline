"""Wire contracts for line hierarchy, leads, reports, and machine messages."""

from pydantic import BaseModel, Field

from .contracts import ConversationResponse

MAX_REPORT_BODY = 2000
MAX_MESSAGE_BODY = 8000


class LeadIn(BaseModel):
    attachment_id: str | None = None


class ChildIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ReportIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_REPORT_BODY)
    notify: bool = False


class Report(BaseModel):
    id: int
    parent_conv_id: str
    child_conv_id: str
    author: str
    author_attachment_id: str | None = None
    body: str
    notify: bool = False
    revision: int = 1
    # When the parent's manager was actually woken. Null on a report that was
    # stored but never announced — no manager appointed, or the wake failed —
    # so a child lead can tell escalation from mere filing.
    notified_at: float | None = None
    # Set while a wake is being delivered, so concurrent escalations coalesce
    # instead of each waking the manager.
    notifying_at: float | None = None
    acknowledged_at: float | None = None
    created_at: float


class AckIn(BaseModel):
    revision: int = Field(ge=1)


class LeadOut(BaseModel):
    attachment_id: str | None = None


class ParentIn(BaseModel):
    parent_id: str | None = None


class CapabilityState(BaseModel):
    kind: str
    role: str
    conv_id: str | None = None
    attachment_id: str | None = None
    is_lead: bool = False
    parent_id: str | None = None
    target_conv_id: str | None = None
    actions: list[str] = Field(default_factory=list)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_MESSAGE_BODY)


class ChildCreatedResponse(BaseModel):
    conversation: ConversationResponse
