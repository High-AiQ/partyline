/** Boot-time write-fence availability and the person-side remedy. */
import { FenceStatusSchema } from "./fence-contracts";
import type { FenceStatus } from "./fence-contracts";
import { request } from "./http";

export const fenceApi = {
  status: (): Promise<FenceStatus> => request("/api/fence/status", { schema: FenceStatusSchema }),
};
