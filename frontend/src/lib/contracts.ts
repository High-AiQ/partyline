/** Runtime-validated contracts shared by the REST and WebSocket boundaries. */

import { z } from "zod";

export const SenderTypeSchema = z.enum(["human", "agent", "system"]);
export type SenderType = z.infer<typeof SenderTypeSchema>;

export const AttachmentStatusSchema = z.enum(["starting", "running", "exited", "detached"]);
export type AttachmentStatus = z.infer<typeof AttachmentStatusSchema>;

export const ConversationSchema = z.object({
  id: z.string(),
  name: z.string(),
  topic: z.string(),
  created_at: z.number(),
  archived_at: z.number().nullable(),
});
export type Conversation = z.infer<typeof ConversationSchema>;

export const ChatMessageSchema = z.object({
  id: z.number().int(),
  conv_id: z.string(),
  sender: z.string(),
  sender_type: SenderTypeSchema,
  body: z.string(),
  created_at: z.number(),
});
export type ChatMessage = z.infer<typeof ChatMessageSchema>;

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
  cli_session: z.string().nullable(),
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

export const ShutdownResultSchema = z.object({
  ok: z.literal(true),
  stopping: z.array(z.string()),
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

export const HelloEventSchema = z.object({
  type: z.literal("hello"),
  conversation_id: z.string(),
  handle: z.string(),
  build: z.string().optional(),
});
export type HelloEvent = z.infer<typeof HelloEventSchema>;

export const MessageEventSchema = z.object({
  type: z.literal("message"),
  message: ChatMessageSchema,
});
export type MessageEvent = z.infer<typeof MessageEventSchema>;

export const AttachmentEventSchema = z.object({
  type: z.literal("attachment"),
  attachment: AttachmentSchema,
});
export type AttachmentEvent = z.infer<typeof AttachmentEventSchema>;

export const AttentionEventSchema = z.object({
  type: z.literal("attention"),
  attachment_id: z.string(),
});
export type AttentionEvent = z.infer<typeof AttentionEventSchema>;

export const ConversationEventSchema = z.object({
  type: z.literal("conversation"),
  conversation: ConversationSchema,
});
export type ConversationEvent = z.infer<typeof ConversationEventSchema>;

export const ConversationArchivedEventSchema = z.object({
  type: z.literal("conversation_archived"),
  conversation_id: z.string(),
});
export type ConversationArchivedEvent = z.infer<typeof ConversationArchivedEventSchema>;

export const ConversationDeletedEventSchema = z.object({
  type: z.literal("conversation_deleted"),
  conversation_id: z.string(),
});
export type ConversationDeletedEvent = z.infer<typeof ConversationDeletedEventSchema>;

export const ErrorEventSchema = z.object({
  type: z.literal("error"),
  conversation_id: z.string(),
  message: z.string(),
});
export type ErrorEvent = z.infer<typeof ErrorEventSchema>;

export const ShutdownEventSchema = z.object({
  type: z.literal("shutdown"),
});
export type ShutdownEvent = z.infer<typeof ShutdownEventSchema>;

export const WireEventSchema = z.discriminatedUnion("type", [
  HelloEventSchema,
  MessageEventSchema,
  AttachmentEventSchema,
  AttentionEventSchema,
  ConversationEventSchema,
  ConversationArchivedEventSchema,
  ConversationDeletedEventSchema,
  ErrorEventSchema,
  ShutdownEventSchema,
]);
export type WireEvent = z.infer<typeof WireEventSchema>;

export const WireHelloCommandSchema = z.object({
  type: z.literal("hello"),
  handle: z.string(),
  client_id: z.string(),
});
export type WireHelloCommand = z.infer<typeof WireHelloCommandSchema>;

export const WireMessageCommandSchema = z.object({
  sender: z.string(),
  body: z.string(),
});
export type WireMessageCommand = z.infer<typeof WireMessageCommandSchema>;
