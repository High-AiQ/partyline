"""Wire contracts for attach presets and lead-scoped staffing."""

from pydantic import BaseModel, Field


class PresetIn(BaseModel):
    title: str
    name: str
    adapter: str = "opencode"
    command: str = ""
    reads_images: bool = False
    can_manage: bool = False
    implements: bool = True
    # 5.3: how many instances of this preset may run at once. 0 means
    # unlimited — a captain preset can hold a live instance per line, the
    # same as a worker preset always could.
    max_instances: int = Field(default=0, ge=0)


class PresetResponse(BaseModel):
    id: str
    title: str
    name: str
    adapter: str
    command: str
    created_at: float
    reads_images: bool = False
    can_manage: bool = False
    implements: bool = True
    max_instances: int = 0


class StaffingTraits(BaseModel):
    reads_images: bool
    can_manage: bool
    implements: bool


class StaffingPreset(StaffingTraits):
    id: str
    title: str
    name: str
    adapter: str


class MatchedPreset(BaseModel):
    id: str
    name: str
    title: str


class StaffingProcess(BaseModel):
    line_id: str
    line: str
    handle: str
    adapter: str
    captain: bool
    matched_preset: MatchedPreset | None = None
    traits: StaffingTraits | None = None


class StaffingLine(BaseModel):
    id: str
    name: str
    accepted_sha: str


class StaffingResponse(BaseModel):
    presets_in_use: bool
    presets: list[StaffingPreset] = Field(default_factory=list)
    processes: list[StaffingProcess] = Field(default_factory=list)
    lines: list[StaffingLine] = Field(default_factory=list)
