import { request } from "./http";
import type { ChatMessage } from "./contracts";
import { ChatMessageSchema } from "./contracts";
import { ReactionRequestSchema } from "./reaction-contracts";

export function toggleReaction(messageId: number, emoji: string): Promise<ChatMessage> {
  return request(`/api/messages/${String(messageId)}/reactions`, {
    schema: ChatMessageSchema,
    method: "POST",
    body: ReactionRequestSchema.parse({ emoji }),
    fallback: "could not toggle reaction",
  });
}

export function removeReaction(messageId: number, emoji: string): Promise<ChatMessage> {
  return request(`/api/messages/${String(messageId)}/reactions/${encodeURIComponent(emoji)}`, {
    schema: ChatMessageSchema,
    method: "DELETE",
    fallback: "could not remove reaction",
  });
}
