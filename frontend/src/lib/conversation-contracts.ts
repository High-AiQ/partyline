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
