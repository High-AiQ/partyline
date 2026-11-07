/** The resource budget as a form: GB in the inputs, bytes on the wire, limits that match the server. */
import type { ResourceSettings } from "./resource-api";

export const GIB = 1024 ** 3;

export interface ResourceDraft {
  maxLiveProcesses: number;
  memoryReserveGb: number;
  defaultLeaseGb: number;
  reservationGb: number;
  warnPercent: number;
  captainCeilingGb: number;
}
export type ResourceErrors = Partial<Record<keyof ResourceDraft, string>>;

export const displayGb = (bytes: number): number => Number((bytes / GIB).toFixed(2));

/** Keep the stored bytes when the shown GB is unchanged, so a save never drifts by rounding. */
export function bytesForSave(gb: number, originalBytes: number): number {
  return displayGb(originalBytes) === Number(gb.toFixed(2)) ? originalBytes : Math.round(gb * GIB);
}

export function draftFromSettings(settings: ResourceSettings): ResourceDraft {
  return {
    maxLiveProcesses: settings.max_live_processes,
    memoryReserveGb: displayGb(settings.memory_reserve_bytes),
    defaultLeaseGb: displayGb(settings.default_process_memory_bytes),
    reservationGb: displayGb(settings.memory_reservation_bytes),
    warnPercent: settings.memory_warn_percent,
    captainCeilingGb: displayGb(settings.memory_captain_ceiling_bytes),
  };
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

export function validateResources(draft: ResourceDraft): ResourceErrors {
  const errors: ResourceErrors = {};
  const { maxLiveProcesses: max, warnPercent: warn } = draft;
  if (!finite(max) || !Number.isInteger(max) || max < 4 || max > 32)
    errors.maxLiveProcesses = "a whole number from 4 to 32";
  if (!finite(draft.memoryReserveGb) || draft.memoryReserveGb < 0) errors.memoryReserveGb = "0 GB or more";
  if (!finite(draft.defaultLeaseGb) || draft.defaultLeaseGb < 0.25)
    errors.defaultLeaseGb = "at least 0.25 GB";
  if (!finite(draft.reservationGb) || draft.reservationGb < 0.25) errors.reservationGb = "at least 0.25 GB";
  if (!finite(warn) || !Number.isInteger(warn) || warn < 50 || warn > 95)
    errors.warnPercent = "a whole percent from 50 to 95";
  if (!finite(draft.captainCeilingGb) || draft.captainCeilingGb < 0.25)
    errors.captainCeilingGb = "at least 0.25 GB";
  return errors;
}

export function resourceBody(draft: ResourceDraft, stored: ResourceSettings) {
  return {
    max_live_processes: draft.maxLiveProcesses,
    memory_reserve_bytes: bytesForSave(draft.memoryReserveGb, stored.memory_reserve_bytes),
    default_process_memory_bytes: bytesForSave(draft.defaultLeaseGb, stored.default_process_memory_bytes),
    memory_reservation_bytes: bytesForSave(draft.reservationGb, stored.memory_reservation_bytes),
    memory_warn_percent: draft.warnPercent,
    memory_captain_ceiling_bytes: bytesForSave(draft.captainCeilingGb, stored.memory_captain_ceiling_bytes),
  };
}
