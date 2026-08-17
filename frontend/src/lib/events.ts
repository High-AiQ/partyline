/** Runtime-validated WebSocket events and commands. */

import { z } from "zod";
import {
  AttachmentSchema,
  ChatMessageSchema,
  ConversationSchema,
  ReattachCandidateSchema,
} from "./contracts";

export const HelloEventSchema = z.object({
  type: z.literal("hello"),
  conversation_id: z.string(),
  handle: z.string(),
  build: z.string().optional(),
  // Required: an old tab must not retain a stale release badge after reconnect.
  version: z.string(),
});
export type HelloEvent = z.infer<typeof HelloEventSchema>;

/** A deliberately lax hello used only to decide whether an old tab reloads. */
export const LegacyHelloSchema = z.object({
  type: z.literal("hello"),
  conversation_id: z.string(),
  build: z.string().optional(),
});
export type LegacyHello = z.infer<typeof LegacyHelloSchema>;

export const MessageEventSchema = z.object({
  type: z.literal("message"),
  message: z.lazy(() => ChatMessageSchema),
});
export type MessageEvent = z.infer<typeof MessageEventSchema>;

export const AttachmentEventSchema = z.object({
  type: z.literal("attachment"),
  attachment: z.lazy(() => AttachmentSchema),
});
export type AttachmentEvent = z.infer<typeof AttachmentEventSchema>;

export const AttentionEventSchema = z.object({
  type: z.literal("attention"),
  attachment_id: z.string(),
});
export type AttentionEvent = z.infer<typeof AttentionEventSchema>;

export const ConversationEventSchema = z.object({
  type: z.literal("conversation"),
  conversation: z.lazy(() => ConversationSchema),
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

export const ReattachOfferEventSchema = z.object({
  type: z.literal("reattach_offer"),
  conversation_id: z.string(),
  token: z.string(),
  attachments: z.array(z.lazy(() => ReattachCandidateSchema)),
  debrief: z.string(),
});
export type ReattachOfferEvent = z.infer<typeof ReattachOfferEventSchema>;

export const ReattachDecisionEventSchema = z.object({
  type: z.literal("reattach_decision"),
  conversation_id: z.string(),
  token: z.string(),
  action: z.enum(["started", "cancelled"]),
});
export type ReattachDecisionEvent = z.infer<typeof ReattachDecisionEventSchema>;

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
  ReattachOfferEventSchema,
  ReattachDecisionEventSchema,
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

export const ReattachActionSchema = z.enum(["accept", "cancel"]);
export type ReattachAction = z.infer<typeof ReattachActionSchema>;

export const WireReattachCommandSchema = z.object({
  type: z.literal("reattach"),
  token: z.string(),
  action: ReattachActionSchema,
});
export type WireReattachCommand = z.infer<typeof WireReattachCommandSchema>;
