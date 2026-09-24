/** The cursor-shaped REST calls used by history, catch-up, and reliable send. */

import { ChatMessageSchema, type ChatMessage } from "./contracts";
import { request } from "./http";
import { MessagePageSchema, type MessagePage } from "./message-page";

export interface MessagePageRequest {
  beforeId?: number;
  afterId?: number;
  limit?: number;
}

export function messagePage(id: string, page: MessagePageRequest = {}): Promise<MessagePage> {
  const query = new URLSearchParams();
  if (page.beforeId !== undefined) query.set("before_id", String(page.beforeId));
  if (page.afterId !== undefined) query.set("after_id", String(page.afterId));
  if (page.limit !== undefined) query.set("limit", String(page.limit));
  const suffix = query.size ? `?${query.toString()}` : "";
  return request(`/api/conversations/${id}/messages${suffix}`, { schema: MessagePageSchema });
}

export function postMessage(convId: string, body: string): Promise<ChatMessage> {
  const text = body.trim();
  if (!text) return Promise.reject(new Error("message body is required"));
  return request(`/api/conversations/${convId}/messages`, {
    schema: ChatMessageSchema,
    method: "POST",
    body: { body: text },
    fallback: "could not send message",
  });
}
