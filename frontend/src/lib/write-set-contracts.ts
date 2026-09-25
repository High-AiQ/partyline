import { z } from "zod";

export const WriteSetGrantRequestSchema = z.object({
  id: z.string(),
  conversation_id: z.string(),
  requester: z.string(),
  path: z.string(),
  created_at: z.number(),
});
export type WriteSetGrantRequest = z.infer<typeof WriteSetGrantRequestSchema>;

export const PendingWriteSetGrantSchema = z.object({
  request: WriteSetGrantRequestSchema.nullable().default(null),
});
export type PendingWriteSetGrant = z.infer<typeof PendingWriteSetGrantSchema>;
