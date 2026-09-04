/** Named boundary contracts for process attachments and their cwd repository. */

import { z } from "zod";

export const AttachmentStatusSchema = z.enum(["starting", "running", "exited", "detached"]);
export type AttachmentStatus = z.infer<typeof AttachmentStatusSchema>;

export const CwdGitStateSchema = z.object({
  sha: z.string().regex(/^[0-9a-f]{7,40}$/),
  dirty: z.boolean(),
});
export type CwdGitState = z.infer<typeof CwdGitStateSchema>;

export const AttachmentCreateRequestSchema = z.object({
  name: z.string(),
  adapter: z.string(),
  command: z.string(),
  cwd: z.string(),
  update: z.boolean().optional(),
});
export type AttachmentCreateRequest = z.infer<typeof AttachmentCreateRequestSchema>;

/**
 * Start a stopped jack over as a brand-new session under the same handle.
 * Both fields are optional: omit them for a blank fresh start. `checkpoint`
 * is a path or a short continuation instruction the new process is pointed
 * at; `after_message_id` is the last chat message the outgoing process
 * incorporated, so messages posted after it are delivered instead of skipped.
 */
export const AttachmentFreshRequestSchema = z.object({
  checkpoint: z.string().optional(),
  after_message_id: z.number().int().positive().optional(),
});
export type AttachmentFreshRequest = z.infer<typeof AttachmentFreshRequestSchema>;

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
