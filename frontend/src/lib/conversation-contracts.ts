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

export const ConversationStarResponseSchema = z.object({
  ok: z.boolean(),
  starred: z.boolean(),
});
export type ConversationStarResponse = z.infer<typeof ConversationStarResponseSchema>;

/**
 * The server owns these enums and can be a release ahead of or behind this bundle
 * (a pulled checkout serves the new UI before the service restarts). An unknown
 * value reads as absent rather than failing the row, the list, or a wire frame.
 */
export const ConversationSchema = z.object({
  captain_mode: z.literal("orchestrator").optional().catch(undefined),
  default_review_policy: z.string().optional(),
  task_status: z
    .enum(["implementing", "idle", "in_review", "approved", "done", "blocked"])
    .nullable()
    .optional()
    .catch(null),
  task_round: z.number().int().nonnegative().nullable().optional(),
  task_mode: z.enum(["full", "light", "express"]).nullable().optional().catch(null),
  task_root_name: z.string().nullable().optional(),
  task_implementer_name: z.string().nullable().optional(),
  task_reviewer_name: z.string().nullable().optional(),
  task_repositories: z.array(z.string()).optional(),
  id: z.string(),
  parent_id: z.string().nullable().optional(),
  /** The line this one continues (a "new chapter"), and its place in that chain. */
  chapter_of: z.string().nullable().optional(),
  chapter: z.number().int().positive().optional(),
  name: z.string(),
  topic: z.string(),
  cwd: z.string().nullable().optional(),
  created_at: z.number(),
  archived_at: z.number().nullable().default(null),
  live_count: z.number().int().nonnegative().default(0),
  starred: z.boolean().optional(),
});
export type Conversation = z.infer<typeof ConversationSchema>;

/** One unreadable line drops only itself: a single bad row once emptied the whole rail. */
export const ConversationListSchema = z.array(z.unknown()).transform((rows) =>
  rows.flatMap((row) => {
    const parsed = ConversationSchema.safeParse(row);
    if (parsed.success) return [parsed.data];
    console.warn("skipping a line the list could not read:", parsed.error.message);
    return [];
  }),
);
