import { z } from "zod";
import { request } from "./http";
import { TranscriptSchema, type Transcript } from "./voice-api";
import { walkthroughWav } from "./walkthrough-audio";

const ok = z.object({ ok: z.literal(true) });
const finished = z.object({ message: z.looseObject({ id: z.number() }) });
export interface WalkthroughResult {
  notes: string;
  segments: Transcript["segments"];
  transcript_text: string;
  transcription_error: boolean;
  mark_pointer: boolean;
  no_input: boolean;
  duration_ms: number;
}

function path(line: string, share: string): string {
  return `/api/conversations/${encodeURIComponent(line)}/walkthroughs/${encodeURIComponent(share)}`;
}

export const walkthroughApi = {
  transcribe: async (
    line: string,
    audio: Blob,
    preset: string | null,
    signal?: AbortSignal,
  ): Promise<Transcript> => {
    const wav = await walkthroughWav(audio, signal);
    const query = new URLSearchParams({ walkthrough: "true" });
    if (preset) query.set("preset", preset);
    return request(`/api/conversations/${encodeURIComponent(line)}/transcribe?${query.toString()}`, {
      schema: TranscriptSchema,
      method: "POST",
      form: wav,
      fallback: "could not transcribe that walkthrough",
      ...(signal ? { signal } : {}),
    });
  },
  arm: (line: string, share: string) => request(path(line, share) + "/arm", { schema: ok, method: "POST" }),
  stop: (line: string, share: string) => request(path(line, share) + "/stop", { schema: ok, method: "POST" }),
  cancel: (line: string, share: string) => request(path(line, share), { schema: ok, method: "DELETE" }),
  finish: (line: string, share: string, body: WalkthroughResult) =>
    request(path(line, share) + "/finish", { schema: finished, method: "POST", body }),
};
