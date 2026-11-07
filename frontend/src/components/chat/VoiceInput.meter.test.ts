import { mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VoiceInput from "./VoiceInput.svelte";
import { room } from "../../state/room.svelte.js";
import { voicePresets } from "../../state/voice-presets.svelte.js";
import { voiceApi } from "../../lib/voice-api";
import { FALLBACK_NOTICE } from "../../lib/mic-device";
import { FakeAudioContext, fakeAudioContext, fakeMicStream, gone } from "../../lib/mic-fakes";
import type { RecorderSources } from "../../lib/voice-recorder";

const conversation = { id: "l", name: "L", topic: "", created_at: 1, archived_at: null, live_count: 0 };

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i++) await tick();
}

function sources(deviceId: string | null = null, rejectFirst = false) {
  const { stream, stop } = fakeMicStream("Headset (Jabra)");
  const getUserMedia = vi.fn<(c: MediaStreamConstraints) => Promise<MediaStream>>(() =>
    Promise.resolve(stream),
  );
  if (rejectFirst) getUserMedia.mockRejectedValueOnce(gone("NotFoundError"));
  const recorder = {
    state: "inactive",
    mimeType: "audio/webm",
    ondataavailable: null as ((e: { data: Blob }) => void) | null,
    onstop: null as (() => void) | null,
    onerror: null,
    start() {
      recorder.state = "recording";
    },
    stop() {
      recorder.state = "inactive";
      recorder.ondataavailable?.({ data: new Blob(["a"]) });
      recorder.onstop?.();
    },
  };
  const result: RecorderSources = {
    getUserMedia,
    createRecorder: () => recorder as unknown as MediaRecorder,
    isTypeSupported: () => true,
    micDeviceId: () => deviceId,
    createAudioContext: fakeAudioContext,
  };
  return { sources: result, getUserMedia, stop };
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeAudioContext.made = [];
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal("MediaRecorder", { isTypeSupported: () => true });
  Object.defineProperty(navigator, "mediaDevices", { value: {}, configurable: true });
  room.conversation = conversation;
  vi.spyOn(voiceApi, "presets").mockResolvedValue({
    default: "a",
    presets: [{ name: "a", kind: "command", available: true }],
  });
  vi.spyOn(voiceApi, "transcribe").mockResolvedValue({ text: "", language: "en", duration: 1, segments: [] });
});

afterEach(() => {
  vi.useRealTimers();
  voicePresets.reset();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  room.leave({ clearRoute: false });
  document.body.replaceChildren();
});

async function recording(setup: ReturnType<typeof sources>) {
  const target = document.body.appendChild(document.createElement("div"));
  const comp = mount(VoiceInput, {
    target,
    props: { box: null, oninserted: () => undefined, sources: setup.sources },
  });
  await tick();
  const button = target.querySelector<HTMLButtonElement>("button.voice");
  button?.click();
  await settle();
  return { target, comp, button };
}

describe("VoiceInput mic meter", () => {
  it("draws the live level and names the mic while recording", async () => {
    const { target, comp } = await recording(sources());
    FakeAudioContext.last().analyser.amplitude = 0.05;
    vi.advanceTimersByTime(100);
    await tick();
    const meter = target.querySelector('[role="meter"]');
    expect(meter?.getAttribute("aria-valuenow")).toBe("30");
    expect(target.querySelector("[title]")?.getAttribute("title")).toBe("Mic: Headset (Jabra)");
    expect(target.querySelector(".mic-silent")).toBeNull();
    void unmount(comp);
  });

  it("says no input was detected after 3 s of silence, and withdraws it when sound returns", async () => {
    const { target, comp } = await recording(sources());
    vi.advanceTimersByTime(2900);
    await tick();
    expect(target.querySelector(".mic-silent")).toBeNull();
    vi.advanceTimersByTime(100);
    await tick();
    expect(target.querySelector(".mic-silent")?.textContent).toContain("no input detected");
    expect(target.querySelector('[role="status"]')?.textContent).toBe("no input detected");
    FakeAudioContext.last().analyser.amplitude = 0.2;
    vi.advanceTimersByTime(100);
    await tick();
    expect(target.querySelector(".mic-silent")).toBeNull();
    void unmount(comp);
  });

  it("opens the chosen device, and tells the person when it fell back to the default", async () => {
    const chosen = sources("jabra-1");
    const { comp } = await recording(chosen);
    expect(chosen.getUserMedia).toHaveBeenCalledWith({ audio: { deviceId: { exact: "jabra-1" } } });
    expect(room.notice).toBeNull();
    void unmount(comp);
    document.body.replaceChildren();

    const missing = sources("gone", true);
    const second = await recording(missing);
    expect(missing.getUserMedia).toHaveBeenLastCalledWith({ audio: true });
    expect(room.notice?.message).toBe(FALLBACK_NOTICE);
    void unmount(second.comp);
  });

  it("frees the audio when it unmounts mid-take", async () => {
    const setup = sources();
    const { comp } = await recording(setup);
    const context = FakeAudioContext.last();
    void unmount(comp);
    expect(context.closed).toBe(true);
    expect(setup.stop).toHaveBeenCalled();
  });

  it("frees the audio when the take is stopped", async () => {
    const setup = sources();
    const { comp, button } = await recording(setup);
    const context = FakeAudioContext.last();
    button?.click();
    await settle();
    expect(context.closed).toBe(true);
    expect(setup.stop).toHaveBeenCalled();
    void unmount(comp);
  });
});
