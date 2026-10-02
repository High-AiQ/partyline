/** Runtime fleet capacity contract and read endpoint. */
import { z } from "zod";
import { request } from "./http";

export const ResourceSnapshotSchema = z.object({
  max_live_processes: z.number().int(),
  memory_reserve_bytes: z.number().int(),
  default_process_memory_bytes: z.number().int(),
  host_ram_bytes: z.number().int(),
  memory_budget_bytes: z.number().int(),
  memory_ceiling_bytes: z.number().int(),
  live_processes: z.number().int(),
  memory_leased_bytes: z.number().int(),
  remaining_processes: z.number().int(),
  remaining_memory_bytes: z.number().int(),
  busiest_line: z.string().nullable(),
});
export type ResourceSnapshot = z.infer<typeof ResourceSnapshotSchema>;

export const ResourceSettingsSchema = ResourceSnapshotSchema.pick({
  max_live_processes: true,
  memory_reserve_bytes: true,
  default_process_memory_bytes: true,
  host_ram_bytes: true,
  memory_budget_bytes: true,
  memory_ceiling_bytes: true,
});
export type ResourceSettings = z.infer<typeof ResourceSettingsSchema>;

export function getResources(): Promise<ResourceSnapshot> {
  return request("/api/resources", { schema: ResourceSnapshotSchema });
}

export function getResourceSettings(): Promise<ResourceSettings> {
  return request("/api/settings/resources", { schema: ResourceSettingsSchema });
}

export function setResourceSettings(
  value: Pick<
    ResourceSettings,
    "max_live_processes" | "memory_reserve_bytes" | "default_process_memory_bytes"
  >,
): Promise<ResourceSettings> {
  return request("/api/settings/resources", {
    schema: ResourceSettingsSchema,
    method: "PUT",
    body: value,
    fallback: "could not save resource settings",
  });
}
