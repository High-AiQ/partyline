import { z } from "zod";

export const WriteSetGrantRequestSchema = z.object({
  id: z.string(),
  conversation_id: z.string(),
  requester: z.string(),
  path: z.string(),
  paths: z.array(z.string()).default([]),
  human_only: z.boolean().default(false),
  already_granted: z.array(z.string()).default([]),
  created_at: z.number(),
});
export type WriteSetGrantRequest = z.infer<typeof WriteSetGrantRequestSchema>;

export const PendingWriteSetGrantSchema = z.object({
  request: WriteSetGrantRequestSchema.nullable().default(null),
});
export type PendingWriteSetGrant = z.infer<typeof PendingWriteSetGrantSchema>;

export const WriteSetApprovalSchema = z.object({
  granted: z.array(z.object({ path: z.string(), granted_at: z.number() })),
});
export type WriteSetApproval = z.infer<typeof WriteSetApprovalSchema>;
