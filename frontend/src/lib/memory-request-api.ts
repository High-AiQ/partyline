import { request } from "./http";
import { PendingMemoryRequestSchema } from "./memory-request-contracts";
import type { PendingMemoryRequestSchema as PendingSchema } from "./memory-request-contracts";
import type { z } from "zod";

type Pending = z.infer<typeof PendingSchema>;
export const memoryRequestApi = {
  pending: (convId: string): Promise<Pending> =>
    request(`/api/conversations/${convId}/memory-request`, { schema: PendingMemoryRequestSchema }),
  approve: (id: string): Promise<Pending> =>
    request(`/api/memory-requests/${id}/approve`, { schema: PendingMemoryRequestSchema, method: "POST" }),
  decline: (id: string): Promise<Pending> =>
    request(`/api/memory-requests/${id}`, { schema: PendingMemoryRequestSchema, method: "DELETE" }),
};
