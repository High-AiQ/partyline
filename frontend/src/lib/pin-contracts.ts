import { z } from "zod";

export const PinSchema = z.object({
  conversation_id: z.string(),
  message_id: z.number().int().positive(),
  alias: z.string().nullable(),
  created_at: z.number(),
  message_available: z.boolean(),
  message_text: z.string().nullable(),
});
export type Pin = z.infer<typeof PinSchema>;

export const PinListSchema = z.array(PinSchema);

export const PinsChangedEventSchema = z.object({
  type: z.literal("pins_changed"),
  conversation_id: z.string(),
  pins: PinListSchema,
});
export type PinsChangedEvent = z.infer<typeof PinsChangedEventSchema>;
