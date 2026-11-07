import { Blob as NodeBlob } from "node:buffer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VoiceListener, speechWav, HANDS_FREE_CAP_MS, PRE_ROLL_MS } from "./voice-listener";
import type { ListenerHooks, ListenerSources } from "./voice-listener";
import { FakeVad } from "./vad-fakes";
import { fakeAudioContext, fakeMicStream, FakeAudioContext, gone } from "./mic-fakes";

beforeEach(() => {
  vi.useFakeTimers();
  FakeAudioContext.made = [];
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
function setup() {
  const mic = fakeMicStream();
  let vad: FakeVad;
  const sources: ListenerSources = {
    getUserMedia: vi.fn().mockResolvedValue(mic.stream),
    micDeviceId: () => "chosen",
    createContext: fakeAudioContext,
    createVad: vi.fn((options: Parameters<ListenerSources["createVad"]>[0]) => {
      vad = new FakeVad(options);
      return Promise.resolve(vad);
    }),
  };
  const hooks: ListenerHooks = { onphase: vi.fn(), ontake: vi.fn(), onerror: vi.fn(), onnotice: vi.fn() };
  const listener = new VoiceListener(sources, hooks);
  return { mic, sources, hooks, listener, vad: () => vad };
}

describe("hands-free Silero listener", () => {
  it("uses the selected microphone, 288 ms frame-aligned pre-roll and configurable pause", async () => {
    const s = setup();
    await s.listener.start(1500);
    expect(s.sources.getUserMedia).toHaveBeenCalledWith({ audio: { deviceId: { exact: "chosen" } } });
    const vad = s.vad();
    await vad.frames(0, 20, 0.2);
    await vad.frames(0.95, 15, 0.3);
    expect(s.hooks.onphase).toHaveBeenLastCalledWith("speaking");
    await vad.frames(0, 45);
    expect(s.hooks.ontake).not.toHaveBeenCalled();
    await vad.frames(0, 1);
    const take = vi.mocked(s.hooks.ontake).mock.calls[0]?.[0];
    // Nine pre-roll frames + 15 speech + floor(1500/32) quiet frames.
    expect(take?.size).toBe(44 + (9 + 15 + 46) * 512 * 2);
    expect(take?.type).toBe("audio/wav");
    expect(s.mic.stop).not.toHaveBeenCalled(); // keep listening through transcription
    s.listener.stop();
    expect(s.mic.stop).toHaveBeenCalledOnce();
    expect(FakeAudioContext.last().closed).toBe(true);
    expect(vad.destroyed).toBe(true);
  });

  it("drops short coughs and low-score noise, and retains a next utterance", async () => {
    const s = setup();
    await s.listener.start(1400);
    const vad = s.vad();
    await vad.frames(0.6, 100); // loudness is irrelevant: low Silero scores cannot start a take
    await vad.frames(0, 50);
    await vad.frames(0.99, 12); // 384 ms < minimum
    await vad.frames(0, 50);
    expect(s.hooks.ontake).not.toHaveBeenCalled();
    for (let i = 0; i < 2; i++) {
      await vad.frames(0.99, 13);
      await vad.frames(0, 50);
    }
    expect(s.hooks.ontake).toHaveBeenCalledTimes(2);
    s.listener.stop();
  });

  it("caps a continuous take and resumes without releasing the selected microphone", async () => {
    const s = setup();
    await s.listener.start(1400);
    await s.vad().frames(0.99, 1900); // more than 60s; encoder also bounds the payload
    await vi.advanceTimersByTimeAsync(HANDS_FREE_CAP_MS - PRE_ROLL_MS);
    const take = vi.mocked(s.hooks.ontake).mock.calls[0]?.[0];
    expect(take?.size).toBe(44 + 60 * 16000 * 2);
    expect(s.vad().listening).toBe(true);
    expect(s.mic.stop).not.toHaveBeenCalled();
    s.listener.stop();
  });

  it("frees a late microphone after cancel and never loads VAD", async () => {
    const s = setup();
    let resolve: ((value: MediaStream) => void) | undefined;
    s.sources.getUserMedia = () =>
      new Promise((done) => {
        resolve = done;
      });
    const start = s.listener.start(1400);
    await Promise.resolve();
    s.listener.stop();
    resolve?.(s.mic.stream);
    await start;
    expect(s.mic.stop).toHaveBeenCalledOnce();
    expect(s.sources.createVad).not.toHaveBeenCalled();
    expect(FakeAudioContext.last().closed).toBe(true);
  });

  it("falls back for an unplugged selection, and frees the mic when model loading fails", async () => {
    const s = setup();
    vi.mocked(s.sources.getUserMedia).mockRejectedValueOnce(gone("NotFoundError"));
    s.sources.createVad = () => Promise.reject(new Error("model unavailable"));
    await s.listener.start(1400);
    expect(s.sources.getUserMedia).toHaveBeenLastCalledWith({ audio: true });
    expect(s.hooks.onnotice).toHaveBeenCalled();
    expect(s.mic.stop).toHaveBeenCalledOnce();
    expect(s.hooks.onerror).toHaveBeenCalled();
    expect(FakeAudioContext.last().closed).toBe(true);
  });

  it("ignores late speech callbacks after stopping", async () => {
    const s = setup();
    await s.listener.start(1400);
    s.listener.stop();
    await s.vad().options.onSpeechStart?.();
    await s.vad().options.onSpeechEnd?.(new Float32Array(16000));
    expect(s.hooks.onphase).toHaveBeenLastCalledWith("off");
    expect(s.hooks.ontake).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});

it("encodes a valid mono 16kHz PCM header with clipped samples", async () => {
  vi.stubGlobal("Blob", NodeBlob);
  const blob = speechWav(new Float32Array([-2, 0, 2]));
  const buffer = await blob.arrayBuffer();
  const view = new DataView(buffer);
  expect(view.getUint32(24, true)).toBe(16000);
  expect(view.getUint16(22, true)).toBe(1);
  expect(view.getUint32(40, true)).toBe(6);
  expect(view.getInt16(44, true)).toBe(-32768);
  expect(view.getInt16(48, true)).toBe(32767);
});
