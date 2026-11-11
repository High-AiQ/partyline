import type { Transcript } from "./voice-api";
import { walkthroughApi } from "./walkthrough-api";

/** A finished take, owned by its line: only an explicit cancel or discard drops it. */
export interface Take {
  audio: Blob;
  line: string;
  share: string;
  cancelled: boolean;
  abort: AbortController | null;
}

export const newTake = (audio: Blob, line: string, share: string): Take => ({
  audio,
  line,
  share,
  cancelled: false,
  abort: null,
});

/** The person gave up on this take: drop it and stop its transcription. */
export function cancelTake(take: Take | null): void {
  if (!take) return;
  take.cancelled = true;
  take.abort?.abort();
}

/** The take's transcript, or `failed` when recognition could not produce one. */
export async function transcribeTake(
  take: Take,
  preset: string | null,
): Promise<{ transcript: Transcript | undefined; failed: boolean }> {
  take.abort = new AbortController();
  try {
    return {
      transcript: await walkthroughApi.transcribe(take.line, take.audio, preset, take.abort.signal),
      failed: false,
    };
  } catch {
    return { transcript: undefined, failed: true };
  }
}
