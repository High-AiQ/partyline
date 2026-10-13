/** Runtime fleet capacity contract and read endpoint. */
import { z } from "zod";
import { request } from "./http";

export const ResourceDefaultsSchema = z.object({
  max_live_processes: z.number().int(),
  memory_reserve_bytes: z.number().int(),
  default_process_memory_bytes: z.number().int(),
  memory_reservation_bytes: z.number().int(),
  memory_warn_percent: z.number().int(),
  memory_captain_ceiling_bytes: z.number().int(),
});

export const ResourceLineUsageSchema = z.object({
  line_id: z.string(),
  line: z.string(),
  usage_bytes: z.number().int(),
});
export type ResourceLineUsage = z.infer<typeof ResourceLineUsageSchema>;

export const DockerWorkloadSummarySchema = z.object({
  running: z.number().int(),
  memory_used_bytes: z.number().int().nullable().default(null),
  uncapped: z.number().int(),
  unattributed: z.number().int(),
  sampled_at: z.number(),
});

export const ResourceSnapshotSchema = z.object({
  max_live_processes: z.number().int(),
  memory_reserve_bytes: z.number().int(),
  default_process_memory_bytes: z.number().int(),
  memory_reservation_bytes: z.number().int(),
  memory_warn_percent: z.number().int(),
  memory_captain_ceiling_bytes: z.number().int(),
  host_ram_bytes: z.number().int(),
  memory_budget_bytes: z.number().int(),
  memory_ceiling_bytes: z.number().int(),
  live_processes: z.number().int(),
  memory_reserved_bytes: z.number().int(),
  memory_cap_bytes: z.number().int(),
  remaining_processes: z.number().int(),
  remaining_memory_bytes: z.number().int(),
  busiest_line: z.string().nullable().default(null),
  host_used_bytes: z.number().int().nullable().default(null),
  host_available_bytes: z.number().int().nullable().default(null),
  partyline_server_bytes: z.number().int().nullable().default(null),
  partyline_processes_bytes: z.number().int().nullable().default(null),
  partyline_used_bytes: z.number().int().nullable().default(null),
  other_used_bytes: z.number().int().nullable().default(null),
  sampled_at: z.number().nullable().default(null),
  top_lines: z.array(ResourceLineUsageSchema),
  docker: DockerWorkloadSummarySchema.nullish(),
});
export type ResourceSnapshot = z.infer<typeof ResourceSnapshotSchema>;

export const ResourceSettingsSchema = ResourceSnapshotSchema.pick({
  max_live_processes: true,
  memory_reserve_bytes: true,
  default_process_memory_bytes: true,
  memory_reservation_bytes: true,
  memory_warn_percent: true,
  memory_captain_ceiling_bytes: true,
  host_ram_bytes: true,
  memory_budget_bytes: true,
  memory_ceiling_bytes: true,
}).extend({ computed_defaults: ResourceDefaultsSchema });
export type ResourceSettings = z.infer<typeof ResourceSettingsSchema>;
export type ResourceDefaults = z.infer<typeof ResourceDefaultsSchema>;

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
