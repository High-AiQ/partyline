"""Wire contracts for fleet-wide process capacity."""

from pydantic import BaseModel, Field


class ResourceSettingsIn(BaseModel):
    max_live_processes: int = Field(ge=4, le=32)
    memory_reserve_bytes: int = Field(ge=0)
    default_process_memory_bytes: int = Field(gt=0)
    memory_reservation_bytes: int = Field(ge=256 * 1024**2)


class ResourceDefaults(BaseModel):
    max_live_processes: int
    memory_reserve_bytes: int
    default_process_memory_bytes: int
    memory_reservation_bytes: int


class ResourceSettings(BaseModel):
    max_live_processes: int
    memory_reserve_bytes: int
    default_process_memory_bytes: int
    memory_reservation_bytes: int
    host_ram_bytes: int
    memory_budget_bytes: int
    memory_ceiling_bytes: int
    computed_defaults: ResourceDefaults


class ResourceSnapshot(BaseModel):
    max_live_processes: int
    memory_reserve_bytes: int
    default_process_memory_bytes: int
    memory_reservation_bytes: int
    host_ram_bytes: int
    memory_budget_bytes: int
    memory_ceiling_bytes: int
    live_processes: int
    memory_reserved_bytes: int
    memory_cap_bytes: int
    remaining_processes: int
    remaining_memory_bytes: int
    busiest_line: str | None = None
