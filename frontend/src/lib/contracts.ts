/** Runtime-validated contracts shared by the REST and WebSocket boundaries. */

import { z } from "zod";

export const SenderTypeSchema = z.enum(["human", "agent", "system"]);
export type SenderType = z.infer<typeof SenderTypeSchema>;

export const AttachmentStatusSchema = z.enum(["starting", "running", "exited", "detached"]);
export type AttachmentStatus = z.infer<typeof AttachmentStatusSchema>;

// These schemas validate two dialects of the same models: REST spells an
// empty field `null`; the wire omits it, because `broadcast()` serializes
// with `exclude_none=True`. A field that can be None on the server must read
// omitted and null as the same fact — `.nullable()` alone rejects the omitted
// spelling, which surfaced as "client/server protocol mismatch" the moment a
// fresh attachment (no cli_session yet) arrived on the wire. Absent means null.

export const ConversationSchema = z.object({
  id: z.string(),
  name: z.string(),
  topic: z.string(),
  created_at: z.number(),
  archived_at: z.number().nullable().default(null),
});
export type Conversation = z.infer<typeof ConversationSchema>;

export const ImageVariantSchema = z.object({
  mime: z.string(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
});
export type ImageVariant = z.infer<typeof ImageVariantSchema>;

export const ImageUrlsSchema = z.object({
  original: z.string(),
  thumb: z.string(),
});
export type ImageUrls = z.infer<typeof ImageUrlsSchema>;

export const ImageRefSchema = z.object({
  id: z.string(),
  title: z.string().max(200).nullable().default(null),
  description: z.string().max(2000).nullable().default(null),
  mime: z.string(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  bytes: z.number().int().nonnegative(),
  thumb: ImageVariantSchema.nullable().default(null),
  urls: ImageUrlsSchema,
});
export type ImageRef = z.infer<typeof ImageRefSchema>;

export const ChatMessageSchema = z.object({
  id: z.number().int(),
  conv_id: z.string(),
  sender: z.string(),
  sender_type: SenderTypeSchema,
  body: z.string(),
  created_at: z.number(),
  images: z.array(ImageRefSchema).default([]),
});
export type ChatMessage = z.infer<typeof ChatMessageSchema>;

export const ImageUploadResponseSchema = z.object({
  message: ChatMessageSchema,
  images: z.array(ImageRefSchema),
});
export type ImageUploadResponse = z.infer<typeof ImageUploadResponseSchema>;

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
});
export type Attachment = z.infer<typeof AttachmentSchema>;

export const AdapterCapabilitiesSchema = z.object({
  resume: z.boolean().optional(),
});
export type AdapterCapabilities = z.infer<typeof AdapterCapabilitiesSchema>;

export const AdapterSchema = z.object({
  id: z.string(),
  name: z.string().optional(),
  version: z.string().optional(),
  description: z.string().optional(),
  entrypoint: z.string().optional(),
  class: z.string().optional(),
  command: z.array(z.string()),
  requires: z.array(z.string()).optional(),
  env_unset: z.array(z.string()).optional(),
  output: z.string().optional(),
  capabilities: AdapterCapabilitiesSchema,
  source: z.string().optional(),
  overrides_bundled: z.boolean().optional().default(false),
});
export type Adapter = z.infer<typeof AdapterSchema>;

export const PresetSchema = z.object({
  id: z.string(),
  title: z.string(),
  name: z.string(),
  adapter: z.string(),
  command: z.string(),
  created_at: z.number(),
});
export type Preset = z.infer<typeof PresetSchema>;

export const RunningProcessSchema = z.object({
  name: z.string(),
  adapter: z.string(),
  conversation: z.string(),
});
export type RunningProcess = z.infer<typeof RunningProcessSchema>;

export const VersionInfoSchema = z.object({
  version: z.string(),
  build: z.string(),
});
export type VersionInfo = z.infer<typeof VersionInfoSchema>;

export const ConversationDetailSchema = z.object({
  conversation: ConversationSchema,
  messages: z.array(ChatMessageSchema),
  attachments: z.array(AttachmentSchema),
});
export type ConversationDetail = z.infer<typeof ConversationDetailSchema>;

export const ReattachCandidateSchema = z.object({
  id: z.string(),
  name: z.string(),
  adapter: z.string(),
});
export type ReattachCandidate = z.infer<typeof ReattachCandidateSchema>;

export const RestartPlanRequestSchema = z.object({
  conversation_id: z.string(),
  debrief: z.string().max(10_000),
});
export type RestartPlanRequest = z.infer<typeof RestartPlanRequestSchema>;

export const RestartPlanSchema = z.object({
  conversation_id: z.string(),
  token: z.string(),
  attachments: z.array(ReattachCandidateSchema),
  debrief: z.string(),
});
export type RestartPlan = z.infer<typeof RestartPlanSchema>;

export const ShutdownRequestSchema = z.object({
  reattach: RestartPlanRequestSchema.optional(),
});
export type ShutdownRequest = z.infer<typeof ShutdownRequestSchema>;

export const ShutdownResultSchema = z.object({
  ok: z.literal(true),
  stopping: z.array(z.string()),
  reattach: RestartPlanSchema.optional(),
});
export type ShutdownResult = z.infer<typeof ShutdownResultSchema>;

export const AdapterImportResultSchema = z.object({
  loaded: z.array(z.string()),
  adapters: z.array(AdapterSchema),
});
export type AdapterImportResult = z.infer<typeof AdapterImportResultSchema>;

export const ArchiveResultSchema = z.object({
  ok: z.literal(true),
  archived: z.literal(true),
  stopped: z.array(z.string()),
  conversation: ConversationSchema,
});
export type ArchiveResult = z.infer<typeof ArchiveResultSchema>;

export const PurgeResultSchema = z.object({
  ok: z.literal(true),
  purged: z.literal(true),
});
export type PurgeResult = z.infer<typeof PurgeResultSchema>;

export const OkResultSchema = z.object({
  ok: z.literal(true),
});
export type OkResult = z.infer<typeof OkResultSchema>;

export const ScreenResultSchema = z.object({
  screen: z.string(),
});
export type ScreenResult = z.infer<typeof ScreenResultSchema>;

export const ApiErrorBodySchema = z.object({
  detail: z.string().optional(),
});
export type ApiErrorBody = z.infer<typeof ApiErrorBodySchema>;

// Keep the original import surface stable while the wire-only contracts live
// in their own file. `events.ts` uses lazy entity schemas to make this
// intentional re-export cycle safe at runtime.
export * from "./events";
