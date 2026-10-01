/** Boundary contract for bounded human-history reads. */

import { z } from "zod";
import { ChatMessageSchema } from "./contracts";

export const MessagePageSchema = z.object({
  messages: z.array(ChatMessageSchema),
  has_more: z.boolean(),
});
export type MessagePage = z.infer<typeof MessagePageSchema>;

export const AroundMessageSchema = z.object({
  messages: z.array(ChatMessageSchema),
  has_more_before: z.boolean(),
  has_more_after: z.boolean(),
});
export type AroundMessage = z.infer<typeof AroundMessageSchema>;
