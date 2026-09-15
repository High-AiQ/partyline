/** A captain's request to restart the service, and a person's decision on it. */
import { PendingRestartSchema } from "./contracts";
import type { PendingRestart } from "./contracts";
import { request } from "./http";

export const restartApi = {
  pending: (): Promise<PendingRestart> => request("/api/restart-request", { schema: PendingRestartSchema }),
  approve: (id: string): Promise<PendingRestart> =>
    request(`/api/restart-request/${id}/approve`, {
      schema: PendingRestartSchema,
      method: "POST",
      fallback: "could not approve the restart",
    }),
  decline: (id: string): Promise<PendingRestart> =>
    request(`/api/restart-request/${id}`, {
      schema: PendingRestartSchema,
      method: "DELETE",
      fallback: "could not decline the restart",
    }),
};
