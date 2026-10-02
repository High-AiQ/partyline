import { z } from "zod";

export const MemoryRequestSchema = z.object({
  id: z.string(),
  attachment_id: z.string(),
  conv_id: z.string(),
  requester: z.string(),
  requester_attachment_id: z.string().nullable(),
  requested_limit: z.string(),
  reason: z.string(),
  created_at: z.number(),
});
export type MemoryRequest = z.infer<typeof MemoryRequestSchema>;
export const PendingMemoryRequestSchema = z.object({ request: MemoryRequestSchema.nullable() });
