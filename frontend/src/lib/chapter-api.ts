/** Start a new chapter of a line: the preview the dialog shows and the action itself. */
import { z } from "zod";
import { request } from "./http";
import { ConversationSchema } from "./conversation-contracts";

export const CaptainPresetSchema = z.object({
  name: z.string(),
  title: z.string(),
  adapter: z.string(),
  command: z.string(),
});
export type CaptainPreset = z.infer<typeof CaptainPresetSchema>;

export const ChapterPreviewSchema = z.object({
  chapter: z.number().int().positive(),
  name: z.string(),
  live_processes: z.number().int().nonnegative(),
  captain_preset: CaptainPresetSchema.nullable(),
  continued_in: z.string().nullable(),
});
export type ChapterPreview = z.infer<typeof ChapterPreviewSchema>;

export const ChapterResponseSchema = z.object({
  conversation: ConversationSchema,
  previous: ConversationSchema,
  captain_preset: CaptainPresetSchema.nullable(),
});
export type ChapterResponse = z.infer<typeof ChapterResponseSchema>;

export const chapterApi = {
  preview: (id: string) =>
    request(`/api/conversations/${id}/chapter`, {
      schema: ChapterPreviewSchema,
      fallback: "could not load the next chapter",
    }),
  start: (id: string, name: string) =>
    request(`/api/conversations/${id}/chapter`, {
      method: "POST",
      body: { name },
      schema: ChapterResponseSchema,
      fallback: "could not start a new chapter",
    }),
};
