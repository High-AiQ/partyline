"""Named HTTP and WebSocket contracts shared by the server and runtime."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .attachment_contracts import AttachmentResponse
from .media_contracts import FileRef
from .line_process_contracts import LineLiveEvent
from .presence_contracts import WorkingEvent

RestartPlanMode = Literal["offer", "automatic"]
RestartPlanScope = Literal["line", "all"]


class ConvIn(BaseModel):
    name: str


class AttachIn(BaseModel):
    name: str
    adapter: str = "opencode"
    command: str = ""
    cwd: str = ""
    update: bool = False


class TopicIn(BaseModel):
    topic: str = ""


class RenameIn(BaseModel):
    name: str


class KeyIn(BaseModel):
    key: str


class CompactResponse(BaseModel):
    ok: Literal[True] = True
    queued: bool


class TerminalGeometry(BaseModel):
    cols: int
    rows: int


class AdapterImportIn(BaseModel):
    repository: str
    ref: str | None = None


class VersionResponse(BaseModel):
    version: str
    build: str
    instance_name: str | None = None


class RunningProcessResponse(BaseModel):
    name: str
    adapter: str
    conversation: str


class AdapterMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    source: str = "bundled"
    overrides_bundled: bool = False
    update_command: list[str] | None = None
    compact_paste: str | None = None


class ConversationResponse(BaseModel):
    id: str
    name: str
    created_at: float
    topic: str = ""
    goal: str = ""
    cwd: str | None = None
    archived_at: float | None = None
    live_count: int = Field(default=0, ge=0)
    parent_id: str | None = None


class MessageResponse(BaseModel):
    id: int
    conv_id: str
    sender: str
    sender_type: Literal["human", "agent", "system"]
    body: str
    created_at: float
    files: list[FileRef] = Field(default_factory=list)
    source_attachment_id: str | None = None
    source_conv_id: str | None = None
    source_conv_name: str | None = None  # the line it was said on, when another
    audience_attachment_id: str | None = None  # a private copy: one process sees it


class FileUploadResponse(BaseModel):
    message: MessageResponse
    files: list[FileRef]


class AttachmentPatchRequest(BaseModel):
    command: str


class ReattachCandidateResponse(BaseModel):
    id: str
    name: str
    adapter: str
    # The line this process lives on; a fleet plan spans lines. Defaulted so an
    # older server that does not send it still parses.
    conversation_id: str = ""


class RestartPlanRequest(BaseModel):
    conversation_id: str
    debrief: str = Field(default="", max_length=10_000)
    mode: RestartPlanMode = "offer"
    # "line" plans the requesting line; "all" plans every live resumable process
    # on every unarchived line. A manual offer is shown to one tab, so only an
    # automatic plan may be fleet-wide.
    scope: RestartPlanScope = "line"


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
    archived_ids: list[str] = []
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


class AttachmentRemovedEvent(BaseModel):
    type: Literal["attachment_removed"] = "attachment_removed"
    attachment_id: str
    conversation_id: str


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
    instance_name: str | None = None


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


class ConversationsChangedEvent(BaseModel):
    type: Literal["conversations_changed"] = "conversations_changed"


class RestartRequestEvent(BaseModel):
    """The pending restart request changed: filed, approved, or declined."""
    type: Literal["restart_request"] = "restart_request"
    request: Any = None


class ReattachCommand(BaseModel):
    type: Literal["reattach"]
    token: str
    action: Literal["accept", "cancel"]


Event = (
    ShutdownEvent
    | MessageEvent
    | AttachmentEvent
    | AttachmentRemovedEvent
    | LineLiveEvent
    | AttentionEvent
    | WorkingEvent
    | ConversationEvent
    | ConversationArchivedEvent
    | ConversationDeletedEvent
    | ConversationsChangedEvent
    | ErrorEvent
    | HelloEvent
    | ReattachOfferEvent
    | ReattachDecisionEvent
    | RestartRequestEvent
)


class HookEventRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: str | None = None
    title: str | None = None
