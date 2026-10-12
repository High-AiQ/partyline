"""Wire contracts for fleet-wide process capacity."""

from pydantic import BaseModel, Field


class ResourceSettingsIn(BaseModel):
    max_live_processes: int = Field(ge=4, le=32)
    memory_reserve_bytes: int = Field(ge=0)
    default_process_memory_bytes: int = Field(gt=0)
    memory_reservation_bytes: int = Field(ge=256 * 1024**2)
    memory_warn_percent: int = Field(default=80, ge=50, le=95)
    memory_captain_ceiling_bytes: int | None = Field(default=None, gt=0)


class ResourceDefaults(BaseModel):
    max_live_processes: int
    memory_reserve_bytes: int
    default_process_memory_bytes: int
    memory_reservation_bytes: int
    memory_warn_percent: int = 80
    memory_captain_ceiling_bytes: int


class ResourceSettings(BaseModel):
    max_live_processes: int
    memory_reserve_bytes: int
    default_process_memory_bytes: int
    memory_reservation_bytes: int
    memory_warn_percent: int
    memory_captain_ceiling_bytes: int
    host_ram_bytes: int
    memory_budget_bytes: int
    memory_ceiling_bytes: int
    computed_defaults: ResourceDefaults


class ResourceLineUsage(BaseModel):
    line_id: str
    line: str
    usage_bytes: int


class ResourceSnapshot(BaseModel):
    max_live_processes: int
    memory_reserve_bytes: int
    default_process_memory_bytes: int
    memory_reservation_bytes: int
    memory_warn_percent: int = 80
    memory_captain_ceiling_bytes: int
    host_ram_bytes: int
    memory_budget_bytes: int
    memory_ceiling_bytes: int
    live_processes: int
    memory_reserved_bytes: int
    memory_cap_bytes: int
    remaining_processes: int
    remaining_memory_bytes: int
    busiest_line: str | None = None
    host_used_bytes: int | None = None
    host_available_bytes: int | None = None
    partyline_server_bytes: int | None = None
    partyline_processes_bytes: int | None = None
    partyline_used_bytes: int | None = None
    other_used_bytes: int | None = None
    sampled_at: float | None = None
    top_lines: list[ResourceLineUsage] = []
    tmp_total_bytes: int | None = None
    tmp_used_bytes: int | None = None
    tmp_partyline_bytes: int | None = None
