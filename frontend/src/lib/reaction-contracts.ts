import { z } from "zod";

export const ReactionEmojiSchema = z.enum(["👍", "❤️", "🎉", "👀", "✅", "❌"]);
export type ReactionEmoji = z.infer<typeof ReactionEmojiSchema>;
export const REACTION_PALETTE: ReactionEmoji[] = ["👍", "❤️", "🎉", "👀", "✅", "❌"];

export const ReactionResponseSchema = z.object({
  emoji: ReactionEmojiSchema,
  reactors: z.array(z.string()),
  mine: z.boolean().default(false),
});
export type ReactionResponse = z.infer<typeof ReactionResponseSchema>;

export const ReactionRequestSchema = z.object({ emoji: ReactionEmojiSchema });
