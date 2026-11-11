import { afterEach, expect, it, vi } from "vitest";
import { walkthroughApi } from "./walkthrough-api";
import { voiceApi } from "./voice-api";
import { request } from "./http";
import { walkthroughWav } from "./walkthrough-audio";

vi.mock("./http", () => ({ request: vi.fn().mockResolvedValue({ text: "", segments: [] }) }));
vi.mock("./walkthrough-audio", () => ({ walkthroughWav: vi.fn() }));
afterEach(() => vi.clearAllMocks());

it("opts walkthroughs into timed transcription using PCM and the selected preset", async () => {
  const input = new Blob(["webm"]);
  const pcm = new Blob(["wav"], { type: "audio/wav" });
  const signal = new AbortController().signal;
  vi.mocked(walkthroughWav).mockResolvedValue(pcm);
  await walkthroughApi.transcribe("line", input, "my preset", signal);
  expect(walkthroughWav).toHaveBeenCalledWith(input, signal);
  expect(request).toHaveBeenCalledWith(
    "/api/conversations/line/transcribe?walkthrough=true&preset=my+preset",
    expect.objectContaining({ form: pcm, method: "POST", signal }),
  );
});

it("leaves composer transcription as a single original audio request", async () => {
  const input = new Blob(["webm"]);
  await voiceApi.transcribe("line", input, null);
  expect(request).toHaveBeenCalledExactlyOnceWith(
    "/api/conversations/line/transcribe",
    expect.objectContaining({ form: input }),
  );
  expect(walkthroughWav).not.toHaveBeenCalled();
});
