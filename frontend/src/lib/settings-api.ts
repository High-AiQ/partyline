/** REST calls for instance-wide settings. */

import { request } from "./http";
import { GlobalProseSchema } from "./settings-contracts";
import type { GlobalProse } from "./settings-contracts";

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
