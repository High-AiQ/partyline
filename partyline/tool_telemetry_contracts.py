"""Content-free tool-call metrics and compact estimated-usage summaries."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .screen_timing_contract import TimingKey, TimingValue


class ImageUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(gt=0, le=100000)
    height: int = Field(gt=0, le=100000)
    provider: Literal["claude", "unknown"]
    estimated_tokens: int | None = Field(default=None, ge=0)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    tool: str = Field(max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    sub_op: str = Field(default="", max_length=80, pattern=r"^[a-z0-9_]*$")
    action: str = Field(default="", max_length=40, pattern=r"^[a-z_]*$")
    then: bool = False
    refresh: bool = False
    query: bool = False
    more: bool = False
    result_bytes: int = Field(ge=0, le=10000000)
    result_chars: int = Field(ge=0, le=10000000)
    estimated_tokens: int = Field(ge=0, le=10000000)
    is_error: bool
    outcome: Literal["ok", "failed", "unconfirmed", "error", "unknown"] = "unknown"
    media_source: Literal["screen", "other"] = "other"
    latency_ms: float = Field(ge=0, le=86400000)
    timestamp: float = Field(ge=0)
    timing: dict[TimingKey, TimingValue] = Field(default_factory=dict, max_length=64)
    images: list[ImageUsage] = Field(default_factory=list, max_length=32)


class ToolBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: list[ToolCall] = Field(max_length=64)


class ToolIngest(BaseModel):
    stored: int


class UsageRow(BaseModel):
    tool: str
    sub_op: str
    action: str = ""
    then: bool = False
    refresh: bool = False
    query: bool = False
    more: bool = False
    calls: int
    total_estimated_tokens: int
    p50_estimated_tokens: int
    p95_estimated_tokens: int
    max_estimated_tokens: int
    errors: int
    p50_latency_ms: float
    unknown_images: int


class UsageSummary(BaseModel):
    conv_id: str
    since: float
    include_descendants: bool
    estimator: str = "utf8_bytes_div_4_v1; images: claude_area_v1 or unknown"
    rows: list[UsageRow]
