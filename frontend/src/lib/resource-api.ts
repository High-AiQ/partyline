/** Fleet capacity read and mutation endpoints. */
import { request } from "./http";
import {
  ResourceSnapshotSchema,
  ResourceSettingsSchema,
  type ResourceSnapshot,
  type ResourceSettings,
} from "./resource-contracts";
export * from "./resource-contracts";

export function getResources(): Promise<ResourceSnapshot> {
  return request("/api/resources", { schema: ResourceSnapshotSchema });
}

export function getResourceSettings(): Promise<ResourceSettings> {
  return request("/api/settings/resources", { schema: ResourceSettingsSchema });
}

export function setResourceSettings(
  value: Pick<
    ResourceSettings,
    | "max_live_processes"
    | "memory_reserve_bytes"
    | "default_process_memory_bytes"
    | "memory_reservation_bytes"
    | "memory_warn_percent"
    | "memory_captain_ceiling_bytes"
  >,
): Promise<ResourceSettings> {
  return request("/api/settings/resources", {
    schema: ResourceSettingsSchema,
    method: "PUT",
    body: value,
    fallback: "could not save resource settings",
  });
}

export function resetResourceSettings(): Promise<ResourceSettings> {
  return request("/api/settings/resources/reset", {
    schema: ResourceSettingsSchema,
    method: "POST",
    fallback: "could not reset resource settings",
  });
}
