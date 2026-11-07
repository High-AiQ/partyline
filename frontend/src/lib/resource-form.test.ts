import { describe, expect, it } from "vitest";
import { GIB, draftFromSettings, resourceBody, validateResources } from "./resource-form";
import type { ResourceSettings } from "./resource-api";

const stored: ResourceSettings = {
  max_live_processes: 8,
  memory_reserve_bytes: 6 * GIB + 140_000_000,
  default_process_memory_bytes: 4 * GIB + 12_345,
  memory_reservation_bytes: GIB,
  memory_warn_percent: 80,
  memory_captain_ceiling_bytes: 8 * GIB,
  host_ram_bytes: 64 * GIB,
  memory_budget_bytes: 58 * GIB,
  memory_ceiling_bytes: 8 * GIB,
  computed_defaults: {
    max_live_processes: 8,
    memory_reserve_bytes: 2 * GIB,
    default_process_memory_bytes: 4 * GIB,
    memory_reservation_bytes: GIB,
    memory_warn_percent: 80,
    memory_captain_ceiling_bytes: 8 * GIB,
  },
};

describe("resource form", () => {
  it("round trips untouched byte values exactly, and converts edited ones", () => {
    const draft = draftFromSettings(stored);
    expect(validateResources(draft)).toEqual({});
    expect(resourceBody(draft, stored).memory_reserve_bytes).toBe(stored.memory_reserve_bytes);
    expect(resourceBody(draft, stored).default_process_memory_bytes).toBe(
      stored.default_process_memory_bytes,
    );
    expect(resourceBody({ ...draft, reservationGb: 0.5 }, stored).memory_reservation_bytes).toBe(GIB / 2);
  });

  it("matches the server's limits field by field", () => {
    const draft = draftFromSettings(stored);
    expect(validateResources({ ...draft, maxLiveProcesses: 3 }).maxLiveProcesses).toBeDefined();
    expect(validateResources({ ...draft, maxLiveProcesses: 33 }).maxLiveProcesses).toBeDefined();
    expect(validateResources({ ...draft, maxLiveProcesses: 4.5 }).maxLiveProcesses).toBeDefined();
    expect(validateResources({ ...draft, memoryReserveGb: -1 }).memoryReserveGb).toBeDefined();
    expect(validateResources({ ...draft, defaultLeaseGb: 0.1 }).defaultLeaseGb).toBeDefined();
    expect(validateResources({ ...draft, reservationGb: Number.NaN }).reservationGb).toBeDefined();
    expect(validateResources({ ...draft, warnPercent: 96 }).warnPercent).toBeDefined();
    expect(validateResources({ ...draft, captainCeilingGb: 0 }).captainCeilingGb).toBeDefined();
  });
});
