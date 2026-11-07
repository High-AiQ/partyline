import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import VoiceInput from "./VoiceInput.svelte";
import { room } from "../../state/room.svelte.js";
import { draft } from "../../state/draft.svelte.js";
import { voicePresets } from "../../state/voice-presets.svelte.js";
import { voiceApi } from "../../lib/voice-api";
import { ApiError } from "../../lib/http";
import type { RecorderSources } from "../../lib/voice-recorder";

afterEach(() => {
  vi.useRealTimers();
  voicePresets.reset();
  voicePresets.choose(null);
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  room.leave({ clearRoute: false });
  draft.text = "";
  document.body.replaceChildren();
});

/** Let every queued promise callback and Svelte flush run; never waits on a clock. */
async function settle(): Promise<void> {
  for (let i = 0; i < 20; i++) await tick();
}

function secure(on: boolean) {
  vi.stubGlobal("isSecureContext", on);
  vi.stubGlobal("MediaRecorder", { isTypeSupported: () => true });
  Object.defineProperty(navigator, "mediaDevices", { value: {}, configurable: true });
}

function sourcesWithTake(): RecorderSources {
  const stream = { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;
  return {
    getUserMedia: () => Promise.resolve(stream),
    createRecorder: () => {
      const r = {
        state: "inactive",
        mimeType: "audio/webm",
        ondataavailable: null as ((e: { data: Blob }) => void) | null,
        onstop: null as (() => void) | null,
        onerror: null,
        start() {
          r.state = "recording";
        },
        stop() {
          r.state = "inactive";
          r.ondataavailable?.({ data: new Blob(["a"]) });
          r.onstop?.();
        },
      };
      return r as unknown as MediaRecorder;
    },
    isTypeSupported: () => true,
  };
}

const conversation = { id: "l", name: "L", topic: "", created_at: 1, archived_at: null, live_count: 0 };

describe("VoiceInput", () => {
  it("is disabled with the reason in an insecure context", async () => {
    secure(false);
    const target = document.body.appendChild(document.createElement("div"));
    const comp = mount(VoiceInput, { target, props: { box: null, oninserted: () => undefined } });
    await tick();
    const button = target.querySelector<HTMLButtonElement>("button.voice");
    expect(button?.disabled).toBe(true);
    void unmount(comp);
  });

  it("disables with the server's reason when the extra is missing", async () => {
    secure(true);
    room.conversation = conversation;
    vi.spyOn(voiceApi, "presets").mockResolvedValue({
      default: "a",
      presets: [{ name: "a", kind: "command", available: false, reason: "needs the extra" }],
    });
    const target = document.body.appendChild(document.createElement("div"));
    const comp = mount(VoiceInput, { target, props: { box: null, oninserted: () => undefined } });
    await settle();
    expect(target.querySelector<HTMLButtonElement>("button.voice")?.disabled).toBe(true);
    void unmount(comp);
  });

  it("records, transcribes and inserts at the caret without sending", async () => {
    secure(true);
    room.conversation = conversation;
    vi.spyOn(voiceApi, "presets").mockResolvedValue({
      default: "a",
      presets: [{ name: "a", kind: "command", available: true }],
    });
    const spy = vi.spyOn(voiceApi, "transcribe").mockResolvedValue({
      text: "hello",
      language: "en",
      duration: 1,
      segments: [],
    });
    const say = vi.spyOn(room, "say");
    draft.openLine(conversation.id);
    draft.text = "ab";
    const box = document.createElement("textarea");
    box.value = "ab";
    document.body.appendChild(box);
    box.setSelectionRange(1, 1);
    const inserted = vi.fn();
    const target = document.body.appendChild(document.createElement("div"));
    const comp = mount(VoiceInput, {
      target,
      props: { box, oninserted: inserted, sources: sourcesWithTake() },
    });
    await tick();
    const button = target.querySelector<HTMLButtonElement>("button.voice");
    button?.click();
    await settle();
    expect(button?.getAttribute("aria-pressed")).toBe("true");
    button?.click();
    await settle();
    expect(draft.text).toBe("a hello b");
    expect(spy).toHaveBeenCalledTimes(1);
    expect(say).not.toHaveBeenCalled();
    void unmount(comp);
  });

  async function failedTake(status: number) {
    secure(true);
    room.conversation = conversation;
    vi.spyOn(voiceApi, "presets").mockResolvedValue({
      default: "a",
      presets: [{ name: "a", kind: "command", available: true }],
    });
    vi.spyOn(voiceApi, "transcribe").mockRejectedValue(new ApiError("take failed", status));
    const target = document.body.appendChild(document.createElement("div"));
    const comp = mount(VoiceInput, {
      target,
      props: { box: null, oninserted: () => undefined, sources: sourcesWithTake() },
    });
    await tick();
    const button = target.querySelector<HTMLButtonElement>("button.voice");
    button?.click();
    await settle();
    expect(button?.getAttribute("aria-pressed")).toBe("true");
    button?.click();
    await settle();
    expect(room.notice?.message).toContain("take failed");
    await tick();
    const disabled = button?.disabled;
    void unmount(comp);
    return disabled;
  }

  it("keeps the mic usable after a failed take (422, 502)", async () => {
    expect(await failedTake(422)).toBe(false);
    document.body.replaceChildren();
    expect(await failedTake(502)).toBe(false);
  });

  it("disables the mic when the server reports it unavailable (503)", async () => {
    expect(await failedTake(503)).toBe(true);
  });

  it("drops a take when the line changes: speech never lands in another line", async () => {
    secure(true);
    room.conversation = conversation;
    vi.spyOn(voiceApi, "presets").mockResolvedValue({
      default: "a",
      presets: [{ name: "a", kind: "command", available: true }],
    });
    let finish: (t: { text: string; language: string; duration: number; segments: [] }) => void = () =>
      undefined;
    vi.spyOn(voiceApi, "transcribe").mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    draft.openLine(conversation.id);
    draft.text = "";
    const target = document.body.appendChild(document.createElement("div"));
    const comp = mount(VoiceInput, {
      target,
      props: { box: null, oninserted: () => undefined, sources: sourcesWithTake() },
    });
    await tick();
    const button = target.querySelector<HTMLButtonElement>("button.voice");
    button?.click();
    await settle();
    expect(button?.getAttribute("aria-pressed")).toBe("true");
    button?.click();
    await settle();
    expect(button?.textContent).toContain("transcribing");
    room.conversation = { ...conversation, id: "other-line" };
    draft.openLine("other-line");
    await tick();
    finish({ text: "secret", language: "en", duration: 1, segments: [] });
    await settle();
    expect(draft.text).toBe("");
    draft.openLine(conversation.id);
    expect(draft.text).toBe("");
    expect(button?.textContent).not.toContain("transcribing");
    void unmount(comp);
  });

  it("tracks unavailability per preset: a 503 on one leaves another usable", async () => {
    secure(true);
    room.conversation = conversation;
    vi.spyOn(voiceApi, "presets").mockResolvedValue({
      default: "a",
      presets: [
        { name: "a", kind: "command", available: true },
        { name: "b", kind: "command", available: true },
      ],
    });
    vi.spyOn(voiceApi, "transcribe").mockRejectedValue(new ApiError("a is down", 503));
    const target = document.body.appendChild(document.createElement("div"));
    const comp = mount(VoiceInput, {
      target,
      props: { box: null, oninserted: () => undefined, sources: sourcesWithTake() },
    });
    await settle();
    expect(target.querySelector("select")).toBeNull();
    const button = target.querySelector<HTMLButtonElement>("button.voice");
    button?.click();
    await settle();
    expect(button?.getAttribute("aria-pressed")).toBe("true");
    button?.click();
    await settle();
    // "a" is marked down; with no pick of its own the mic falls through to "b" and stays usable.
    expect(voicePresets.listing?.presets.find((entry) => entry.name === "a")?.available).toBe(false);
    expect(voicePresets.active).toBe("b");
    expect(button?.disabled).toBe(false);
    // A remembered pick that is down falls through the same way.
    voicePresets.choose("a");
    await settle();
    expect(voicePresets.active).toBe("b");
    void unmount(comp);
  });

  it("never traps a live mic: presets that arrive unavailable mid-take leave stop enabled", async () => {
    secure(true);
    room.conversation = conversation;
    let resolvePresets: (v: Awaited<ReturnType<typeof voiceApi.presets>>) => void = () => undefined;
    vi.spyOn(voiceApi, "presets").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePresets = resolve;
        }),
    );
    const transcribe = vi
      .spyOn(voiceApi, "transcribe")
      .mockResolvedValue({ text: "hi", language: "en", duration: 1, segments: [] });
    const target = document.body.appendChild(document.createElement("div"));
    const comp = mount(VoiceInput, {
      target,
      props: { box: null, oninserted: () => undefined, sources: sourcesWithTake() },
    });
    await tick();
    const button = target.querySelector<HTMLButtonElement>("button.voice");
    button?.click();
    await settle();
    expect(button?.getAttribute("aria-pressed")).toBe("true");
    resolvePresets({
      default: "a",
      presets: [{ name: "a", kind: "command", available: false, reason: "not installed" }],
    });
    await tick();
    await settle();
    expect(button?.disabled).toBe(false);
    button?.click();
    await settle();
    expect(transcribe).toHaveBeenCalled();
    // Afterwards the reason shows and the mic is disabled again.
    await settle();
    expect(button?.disabled).toBe(true);
    void unmount(comp);
  });

  it("lets the person cancel while the permission prompt is open", async () => {
    secure(true);
    room.conversation = conversation;
    vi.spyOn(voiceApi, "presets").mockResolvedValue({
      default: "a",
      presets: [{ name: "a", kind: "command", available: true }],
    });
    const track = { stop: vi.fn() };
    const stream = { getTracks: () => [track] } as unknown as MediaStream;
    let grant: (s: MediaStream) => void = () => undefined;
    const sources = {
      ...sourcesWithTake(),
      getUserMedia: () =>
        new Promise<MediaStream>((resolve) => {
          grant = resolve;
        }),
    };
    const target = document.body.appendChild(document.createElement("div"));
    const comp = mount(VoiceInput, {
      target,
      props: { box: null, oninserted: () => undefined, sources },
    });
    await tick();
    const button = target.querySelector<HTMLButtonElement>("button.voice");
    button?.click();
    await tick();
    expect(button?.disabled).toBe(false);
    button?.click();
    grant(stream);
    await settle();
    expect(track.stop).toHaveBeenCalled();
    expect(button?.getAttribute("aria-pressed")).toBe("false");
    void unmount(comp);
  });
});
