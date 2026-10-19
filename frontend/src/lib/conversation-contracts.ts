import { z } from "zod";

export const SkippedPurgeSchema = z.object({
  id: z.string(),
  reason: z.string(),
});
export type SkippedPurge = z.infer<typeof SkippedPurgeSchema>;

export const PurgeAllResponseSchema = z.object({
  purged: z.array(z.string()),
  skipped: z.array(SkippedPurgeSchema),
});
export type PurgeAllResponse = z.infer<typeof PurgeAllResponseSchema>;

export const ConversationSchema = z.object({
  captain_mode: z.enum(["manager_tree", "orchestrator"]).optional(),
  default_review_policy: z.string().optional(),
  task_status: z.enum(["implementing", "in_review", "approved", "done", "blocked"]).nullable().optional(),
  task_round: z.number().int().nonnegative().nullable().optional(),
  task_root_name: z.string().nullable().optional(),
  task_implementer_name: z.string().nullable().optional(),
  task_reviewer_name: z.string().nullable().optional(),
  id: z.string(),
  parent_id: z.string().nullable().optional(),
  name: z.string(),
  topic: z.string(),
  cwd: z.string().nullable().optional(),
  created_at: z.number(),
  archived_at: z.number().nullable().default(null),
  live_count: z.number().int().nonnegative().default(0),
});
export type Conversation = z.infer<typeof ConversationSchema>;
