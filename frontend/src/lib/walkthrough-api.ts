import { z } from "zod";
import { request } from "./http";
import type { Transcript } from "./voice-api";

const ok = z.object({ ok: z.literal(true) });
const finished = z.object({ message: z.looseObject({ id: z.number() }) });
export interface WalkthroughResult {
  notes: string;
  segments: Transcript["segments"];
  transcription_error: boolean;
  mark_pointer: boolean;
}

function path(line: string, share: string): string {
  return `/api/conversations/${encodeURIComponent(line)}/walkthroughs/${encodeURIComponent(share)}`;
}

export const walkthroughApi = {
  arm: (line: string, share: string) => request(path(line, share) + "/arm", { schema: ok, method: "POST" }),
  stop: (line: string, share: string) => request(path(line, share) + "/stop", { schema: ok, method: "POST" }),
  cancel: (line: string, share: string) => request(path(line, share), { schema: ok, method: "DELETE" }),
  finish: (line: string, share: string, body: WalkthroughResult) =>
    request(path(line, share) + "/finish", { schema: finished, method: "POST", body }),
};
