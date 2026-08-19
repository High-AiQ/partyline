"""Named HTTP and WebSocket contracts shared by the server and runtime."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .media_contracts import ImageRef
from .presence_contracts import PresenceState, WorkingEvent

RestartPlanMode = Literal["offer", "automatic"]


class ConvIn(BaseModel):
    name: str


class AttachIn(BaseModel):
    name: str
    adapter: str = "opencode"
    command: str = ""
    cwd: str = ""


class TopicIn(BaseModel):
    topic: str = ""
    sender: str = ""


class RenameIn(BaseModel):
    name: str
    sender: str = ""


class PresetIn(BaseModel):
    title: str
    name: str
    adapter: str = "opencode"
    command: str = ""


class KeyIn(BaseModel):
    key: str


class TerminalGeometry(BaseModel):
    cols: int
    rows: int


class AdapterImportIn(BaseModel):
    repository: str
    ref: str | None = None


class VersionResponse(BaseModel):
    version: str
    build: str


class RunningProcessResponse(BaseModel):
    name: str
    adapter: str
    conversation: str


class AdapterMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    source: str = "bundled"
    overrides_bundled: bool = False


class ConversationResponse(BaseModel):
    id: str
    name: str
    created_at: float
    topic: str = ""
    archived_at: float | None = None


class MessageResponse(BaseModel):
    id: int
    conv_id: str
    sender: str
    sender_type: Literal["human", "agent", "system"]
    body: str
    created_at: float
    images: list[ImageRef] = Field(default_factory=list)


class ImageUploadResponse(BaseModel):
    message: MessageResponse
    images: list[ImageRef]


class AttachmentResponse(BaseModel):
    id: str
    conv_id: str
    name: str
    adapter: str
    command: list[str]
    cwd: str
    status: Literal["starting", "running", "exited", "detached"]
    last_seen: int
    created_at: float
    cli_session: str | None = None


class AttachmentCommandRequest(BaseModel):
    command: str


class PresetResponse(BaseModel):
    id: str
    title: str
    name: str
    adapter: str
    command: str
    created_at: float


class ConversationDetailResponse(BaseModel):
    conversation: ConversationResponse
    messages: list[MessageResponse]
    attachments: list[AttachmentResponse]
    # Which attachments are mid-turn right now. A tab that opens or reconnects
    # during someone's turn would otherwise show nothing until the next
    # transition — the indicator would be blank exactly when it matters.
    working: list[str] = []
    # None means the server has not adopted structured presence yet; clients
    # keep consuming the legacy list until the endpoint supplies this field.
    # This server always supplies it, including idle tombstones: their
    # revisions stop a buffered pre-snapshot event relighting a cleared badge.
    presence: list[PresenceState] | None = None


class ReattachCandidateResponse(BaseModel):
    id: str
    name: str
    adapter: str


class RestartPlanRequest(BaseModel):
    conversation_id: str
    debrief: str = Field(default="", max_length=10_000)
    mode: RestartPlanMode = "offer"


class RestartPlanResponse(BaseModel):
    conversation_id: str
    token: str
    attachments: list[ReattachCandidateResponse]
    debrief: str


class ShutdownRequest(BaseModel):
    reattach: RestartPlanRequest | None = None


class ShutdownResponse(BaseModel):
    ok: bool
    stopping: list[str]
    reattach: RestartPlanResponse | None = None


class AdapterImportResponse(BaseModel):
    loaded: list[str]
    adapters: list[AdapterMetadataResponse]


class LoadedResponse(BaseModel):
    loaded: list[str]


class AdapterRemoveResponse(BaseModel):
    ok: bool
    message: str


class ArchiveResponse(BaseModel):
    ok: bool
    archived: bool
    stopped: list[str]
    conversation: ConversationResponse


class PurgeResponse(BaseModel):
    ok: bool
    purged: bool


class OkResponse(BaseModel):
    ok: bool


class ScreenResponse(BaseModel):
    screen: str


class ShutdownEvent(BaseModel):
    type: Literal["shutdown"] = "shutdown"


class MessageEvent(BaseModel):
    type: Literal["message"] = "message"
    message: MessageResponse


class AttachmentEvent(BaseModel):
    type: Literal["attachment"] = "attachment"
    attachment: AttachmentResponse


class AttentionEvent(BaseModel):
    type: Literal["attention"] = "attention"
    attachment_id: str


class ConversationEvent(BaseModel):
    type: Literal["conversation"] = "conversation"
    conversation: ConversationResponse


class ConversationArchivedEvent(BaseModel):
    type: Literal["conversation_archived"] = "conversation_archived"
    conversation_id: str


class ConversationDeletedEvent(BaseModel):
    type: Literal["conversation_deleted"] = "conversation_deleted"
    conversation_id: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    conversation_id: str
    message: str


class HelloEvent(BaseModel):
    type: Literal["hello"] = "hello"
    conversation_id: str
    handle: str
    build: str | None = None
    version: str


class ReattachOfferEvent(BaseModel):
    type: Literal["reattach_offer"] = "reattach_offer"
    conversation_id: str
    token: str
    attachments: list[ReattachCandidateResponse]
    debrief: str


class ReattachDecisionEvent(BaseModel):
    type: Literal["reattach_decision"] = "reattach_decision"
    conversation_id: str
    token: str
    action: Literal["started", "cancelled"]


class ReattachCommand(BaseModel):
    type: Literal["reattach"]
    token: str
    action: Literal["accept", "cancel"]


Event = (
    ShutdownEvent
    | MessageEvent
    | AttachmentEvent
    | AttentionEvent
    | WorkingEvent
    | ConversationEvent
    | ConversationArchivedEvent
    | ConversationDeletedEvent
    | ErrorEvent
    | HelloEvent
    | ReattachOfferEvent
    | ReattachDecisionEvent
)


class HookEventRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str | None = None
    title: str | None = None
