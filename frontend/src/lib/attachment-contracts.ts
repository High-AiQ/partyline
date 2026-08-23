/** Named boundary contracts for process attachments and their cwd repository. */

import { z } from "zod";

export const AttachmentStatusSchema = z.enum(["starting", "running", "exited", "detached"]);
export type AttachmentStatus = z.infer<typeof AttachmentStatusSchema>;

export const CwdGitStateSchema = z.object({
  sha: z.string().regex(/^[0-9a-f]{7,40}$/),
  dirty: z.boolean(),
});
export type CwdGitState = z.infer<typeof CwdGitStateSchema>;

export const AttachmentSchema = z.object({
  id: z.string(),
  conv_id: z.string(),
  name: z.string(),
  adapter: z.string(),
  command: z.array(z.string()),
  cwd: z.string(),
  status: AttachmentStatusSchema,
  last_seen: z.number().int(),
  created_at: z.number(),
  cli_session: z.string().nullable().default(null),
  cwd_git: CwdGitStateSchema.nullable().default(null),
});
export type Attachment = z.infer<typeof AttachmentSchema>;
