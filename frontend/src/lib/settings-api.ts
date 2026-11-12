/** REST calls for instance-wide settings. */

import { request } from "./http";
import { GlobalProseSchema, MaxCompactionsSchema } from "./settings-contracts";
import type { GlobalProse, MaxCompactions } from "./settings-contracts";

export function getGlobalProse(): Promise<GlobalProse> {
  return request("/api/settings/global_prose", { schema: GlobalProseSchema });
}

export function setGlobalProse(value: string | null): Promise<GlobalProse> {
  return request("/api/settings/global_prose", {
    schema: GlobalProseSchema,
    method: "PUT",
    body: { value },
    fallback: "could not save global prose",
  });
}

export function getMaxCompactions(): Promise<MaxCompactions> {
  return request("/api/settings/max_compactions", { schema: MaxCompactionsSchema });
}

export function setMaxCompactions(value: number): Promise<MaxCompactions> {
  return request("/api/settings/max_compactions", {
    schema: MaxCompactionsSchema,
    method: "PUT",
    body: { value },
    fallback: "could not save the compaction limit",
  });
}
