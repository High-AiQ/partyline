"""Shared JSON contracts and limits for the native screen helper protocol."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 4 * 1024 * 1024
FRAME_BUFFER_SIZE = 20
PAIR_CODE_TTL = 300
HEARTBEAT_SECONDS = 15
HEARTBEAT_TIMEOUT = 45
DEFAULT_MAX_FPS = 1
DEFAULT_LONG_EDGE = 1280
DEFAULT_MIN_CHANGE = 0.02


class PairResponse(BaseModel):
    code: str
    expires_in: int


class PairClaim(BaseModel):
    code: str = Field(min_length=1, max_length=8)
    device_name: str = Field(max_length=120)
    os: str = Field(max_length=40)


class PairClaimResponse(BaseModel):
    device_id: str
    token: str


class Region(BaseModel):
    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class Monitor(BaseModel):
    id: str | int
    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    scale: float = Field(gt=0)
    primary: bool


class Pointer(BaseModel):
    x: int
    y: int
    visible: bool
    captured: bool = False  # hidden/captured OS cursor; visible still denotes region membership


class HelperMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str


class HelperHello(HelperMessage):
    type: Literal["hello"]
    protocol: Literal[1]
    device_name: str
    os: str
    helper_version: str
    monitors: list[Monitor]
    control: int = 0  # agent-control protocol version; absent on helpers that predate it
    tools: int = 0  # local-tools protocol version; absent on helpers that predate it


class HelperFrame(HelperMessage):
    type: Literal["frame"]
    share_id: str
    request_id: str | None = None
    ts_ms: int = Field(ge=0)
    region: Region
    out_width: int = Field(gt=0)
    out_height: int = Field(gt=0)
    pointer: Pointer | None = None
    mime: str = Field(min_length=1, max_length=128)


class HelperPreview(HelperMessage):
    type: Literal["preview"]
    request_id: str
    monitor_id: str | int
    out_width: int = Field(gt=0)
    out_height: int = Field(gt=0)
    mime: str = Field(min_length=1, max_length=128)


class ShareCommand(BaseModel):
    type: Literal["start_share"]
    share_id: str
    conv_id: str
    line_name: str
    requested_by: str
    region: Region
    max_fps: int = DEFAULT_MAX_FPS
    long_edge: int = DEFAULT_LONG_EDGE
    min_change: float = DEFAULT_MIN_CHANGE
    control: bool = False  # the person asked for agent control with this share


class ShareAccepted(HelperMessage):
    type: Literal["share_accepted"]
    share_id: str


class ShareEnded(HelperMessage):
    type: Literal["share_declined", "share_stopped"]
    share_id: str
    reason: str


class HelperError(HelperMessage):
    type: Literal["error"]
    request_id: str | None = None
    message: str


class StopShare(BaseModel):
    type: Literal["stop_share"] = "stop_share"
    share_id: str


class Snap(BaseModel):
    type: Literal["snap"] = "snap"
    share_id: str
    request_id: str


class GetPreview(BaseModel):
    type: Literal["get_preview"] = "get_preview"
    request_id: str
    monitor_id: str | int
    long_edge: int = Field(gt=0)


class Heartbeat(BaseModel):
    type: Literal["ping", "pong"]
