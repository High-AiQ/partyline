/** Voice input REST calls: speech presets and one-shot transcription. */
import { z } from "zod";
import { request } from "./http";

const PresetSchema = z.object({
  name: z.string(),
  kind: z.string(),
  available: z.boolean(),
  reason: z.string().nullable().optional(),
  model: z.string().nullable().optional(),
});
export type VoicePreset = z.infer<typeof PresetSchema>;

const ListingSchema = z.object({ default: z.string(), presets: z.array(PresetSchema) });
export type VoiceListing = z.infer<typeof ListingSchema>;

export const TranscriptSchema = z.object({
  text: z.string(),
  language: z.string(),
  duration: z.number(),
  segments: z
    .array(
      z.object({ start: z.number(), end: z.number(), text: z.string(), utterance: z.boolean().optional() }),
    )
    .default([]),
});
export type Transcript = z.infer<typeof TranscriptSchema>;

export const voiceApi = {
  presets: (): Promise<VoiceListing> =>
    request("/api/transcribe/presets", { schema: ListingSchema, fallback: "could not check voice input" }),
  transcribe: (
    conversationId: string,
    audio: Blob,
    preset: string | null,
    signal?: AbortSignal,
  ): Promise<Transcript> =>
    request(
      `/api/conversations/${conversationId}/transcribe${preset ? `?preset=${encodeURIComponent(preset)}` : ""}`,
      {
        schema: TranscriptSchema,
        method: "POST",
        form: audio,
        fallback: "could not transcribe that recording",
        ...(signal ? { signal } : {}),
      },
    ),
};
