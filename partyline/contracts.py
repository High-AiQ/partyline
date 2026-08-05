"""Named HTTP and WebSocket contracts shared by the server and runtime."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


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


class ShutdownResponse(BaseModel):
    ok: bool
    stopping: list[str]


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


Event = (
    ShutdownEvent
    | MessageEvent
    | AttachmentEvent
    | AttentionEvent
    | ConversationEvent
    | ConversationArchivedEvent
    | ConversationDeletedEvent
    | ErrorEvent
    | HelloEvent
)


class HookEventRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str | None = None
    title: str | None = None
