"""Named HTTP and WebSocket contracts shared by the server and runtime."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .attachment_contracts import AttachmentResponse
from .media_contracts import FileRef
from .line_process_contracts import LineLiveEvent
from .presence_contracts import WorkingEvent

RestartPlanMode = Literal["offer", "automatic"]


class ConvIn(BaseModel):
    name: str


class AttachIn(BaseModel):
    name: str
    adapter: str = "opencode"
    command: str = ""
    cwd: str = ""
    update: bool = False


# Neither carries a sender: who changed a topic or name is derived from the
# authenticated principal, never from a client-supplied field.
class TopicIn(BaseModel):
    topic: str = ""


class RenameIn(BaseModel):
    name: str


class PresetIn(BaseModel):
    title: str
    name: str
    adapter: str = "opencode"
    command: str = ""


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
    archived_at: float | None = None
    live_count: int = Field(default=0, ge=0)


class MessageResponse(BaseModel):
    id: int
    conv_id: str
    sender: str
    sender_type: Literal["human", "agent", "system"]
    body: str
    created_at: float
    files: list[FileRef] = Field(default_factory=list)


class FileUploadResponse(BaseModel):
    message: MessageResponse
    files: list[FileRef]


class AttachmentPatchRequest(BaseModel):
    command: str


class PresetResponse(BaseModel):
    id: str
    title: str
    name: str
    adapter: str
    command: str
    created_at: float


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


class ReattachCommand(BaseModel):
    type: Literal["reattach"]
    token: str
    action: Literal["accept", "cancel"]


Event = (
    ShutdownEvent
    | MessageEvent
    | AttachmentEvent
    | LineLiveEvent
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
