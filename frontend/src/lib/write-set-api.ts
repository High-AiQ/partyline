/** A line's request for extra write-set scope, and a person's decision on it. */
import { PendingWriteSetGrantSchema } from "./write-set-contracts";
import type { PendingWriteSetGrant } from "./write-set-contracts";
import { request } from "./http";

export const writeSetApi = {
  pending: (convId: string): Promise<PendingWriteSetGrant> =>
    request(`/api/conversations/${convId}/write-set/request`, { schema: PendingWriteSetGrantSchema }),
  approve: (convId: string, id: string): Promise<PendingWriteSetGrant> =>
    request(`/api/conversations/${convId}/write-set/request/${id}/approve`, {
      schema: PendingWriteSetGrantSchema,
      method: "POST",
      fallback: "could not approve the write-set request",
    }),
  decline: (convId: string, id: string): Promise<PendingWriteSetGrant> =>
    request(`/api/conversations/${convId}/write-set/request/${id}`, {
      schema: PendingWriteSetGrantSchema,
      method: "DELETE",
      fallback: "could not decline the write-set request",
    }),
};
