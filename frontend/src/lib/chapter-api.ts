/** Start a new chapter of a line: the preview the dialog shows and the action itself. */
import { z } from "zod";
import { request } from "./http";

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

/** A line write's reply: where the line is and how long its goal is. The line itself is read whole. */
export const LineStatusSchema = z.object({
  id: z.string(),
  name: z.string(),
  parent_id: z.string().nullable(),
  cwd: z.string().nullable(),
  goal_chars: z.number().int().nonnegative(),
});
export type LineStatus = z.infer<typeof LineStatusSchema>;

export const ChapterResponseSchema = z.object({
  conversation: LineStatusSchema,
  previous: LineStatusSchema,
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
