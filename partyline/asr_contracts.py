"""Named request, response and event models for speech-preset settings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .transcribe_routes import TranscribeResponse

Kind = Literal["faster-whisper", "openai-compatible", "command"]


class AsrFields(BaseModel):
    """Every field any kind takes. ``extra="forbid"``: there is no field a key could ride in on."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    model: str | None = Field(None, max_length=200)
    device: str | None = Field(None, max_length=20)
    compute_type: str | None = Field(None, max_length=40)
    model_dir: str | None = Field(None, max_length=1000)
    base_url: str | None = Field(None, max_length=1000)
    api_key_env: str | None = Field(None, max_length=64)
    response_format: Literal["verbose_json", "json"] | None = None
    language: str | None = Field(None, max_length=20)
    prompt: str | None = Field(None, max_length=2000)
    argv: list[str] | None = Field(None, max_length=64)
    timeout: float | None = None


class AsrPresetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    fields: AsrFields = AsrFields()


class AsrPresetCreate(AsrPresetIn):
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,32}$")


class AsrPresetView(BaseModel):
    name: str
    kind: str
    source: Literal["config", "builtin", "database"]
    editable: bool
    overrides_config: bool
    is_default: bool
    can_be_default: bool
    available: bool
    reason: str | None = None
    model: str | None = None
    fields: AsrFields
    key_env: str | None = None
    key_set: bool | None = None


class AsrSettings(BaseModel):
    default: str
    presets: list[AsrPresetView]


class AsrDefaultIn(BaseModel):
    name: str


class AsrOrderIn(BaseModel):
    names: list[str]


class AsrTestResult(TranscribeResponse):
    preset: str
    latency_ms: int


class AsrPresetsChangedEvent(BaseModel):
    type: Literal["asr_presets_changed"] = "asr_presets_changed"
    settings: AsrSettings
