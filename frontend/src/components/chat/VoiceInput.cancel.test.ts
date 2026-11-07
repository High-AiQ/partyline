import { mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VoiceInput from "./VoiceInput.svelte";
import { room } from "../../state/room.svelte.js";
import { draft } from "../../state/draft.svelte.js";
import { session } from "../../state/session.svelte.js";
import { RETRY_BASE_MS, voicePresets } from "../../state/voice-presets.svelte.js";
import { voiceApi } from "../../lib/voice-api";
import type { Transcript, VoiceListing } from "../../lib/voice-api";
import type { RecorderSources } from "../../lib/voice-recorder";

const conversation = { id: "l", name: "L", topic: "", created_at: 1, archived_at: null, live_count: 0 };
const ONE: VoiceListing = { default: "a", presets: [{ name: "a", kind: "command", available: true }] };

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i++) await tick();
}

function take(track = { stop: vi.fn() }): RecorderSources {
  const stream = { getTracks: () => [track] } as unknown as MediaStream;
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

/** A composer row: the mic sits beside the message box, as in Composer.svelte. */
function composer(sources: RecorderSources) {
  const row = document.body.appendChild(document.createElement("div"));
  const box = row.appendChild(document.createElement("textarea"));
  const comp = mount(VoiceInput, { target: row, props: { box, oninserted: () => undefined, sources } });
  const mic = () => row.querySelector<HTMLButtonElement>("button.voice");
  const cancel = () => row.querySelector<HTMLButtonElement>('button[aria-label="cancel voice message"]');
  return { row, box, comp, mic, cancel };
}

beforeEach(() => {
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal("MediaRecorder", { isTypeSupported: () => true });
  Object.defineProperty(navigator, "mediaDevices", { value: {}, configurable: true });
  room.conversation = conversation;
  draft.openLine(conversation.id);
  draft.text = "";
});

afterEach(() => {
  vi.useRealTimers();
  voicePresets.reset();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  room.leave({ clearRoute: false });
  draft.text = "";
  document.body.replaceChildren();
});

describe("VoiceInput cancel", () => {
  it("cancels while recording: nothing uploaded, mic released at once", async () => {
    vi.spyOn(voiceApi, "presets").mockResolvedValue(ONE);
    const transcribe = vi.spyOn(voiceApi, "transcribe");
    const track = { stop: vi.fn() };
    const ui = composer(take(track));
    await settle();
    expect(ui.cancel()).toBeNull();
    ui.mic()?.click();
    await settle();
    expect(ui.mic()?.getAttribute("aria-pressed")).toBe("true");
    ui.cancel()?.click();
    await settle();
    expect(track.stop).toHaveBeenCalled();
    expect(transcribe).not.toHaveBeenCalled();
    expect(ui.mic()?.getAttribute("aria-pressed")).toBe("false");
    expect(ui.cancel()).toBeNull();
    expect(draft.text).toBe("");
    void unmount(ui.comp);
  });

  it("cancels while transcribing: the request is aborted and a late result is ignored", async () => {
    vi.spyOn(voiceApi, "presets").mockResolvedValue(ONE);
    let finish: (t: Transcript) => void = () => undefined;
    let signal: AbortSignal | undefined;
    vi.spyOn(voiceApi, "transcribe").mockImplementation((_line, _audio, _preset, abort) => {
      signal = abort;
      return new Promise((resolve) => {
        finish = resolve;
      });
    });
    const ui = composer(take());
    await settle();
    ui.mic()?.click();
    await settle();
    ui.mic()?.click();
    await settle();
    expect(ui.mic()?.textContent).toContain("transcribing");
    ui.cancel()?.click();
    await settle();
    expect(signal?.aborted).toBe(true);
    expect(ui.mic()?.textContent).not.toContain("transcribing");
    finish({ text: "too late", language: "en", duration: 1, segments: [] });
    await settle();
    expect(draft.text).toBe("");
    expect(ui.mic()?.disabled).toBe(false);
    void unmount(ui.comp);
  });

  it("Escape in the composer cancels the take and goes no further", async () => {
    vi.spyOn(voiceApi, "presets").mockResolvedValue(ONE);
    const transcribe = vi.spyOn(voiceApi, "transcribe");
    const outer = vi.fn();
    window.addEventListener("keydown", outer);
    const ui = composer(take());
    await settle();
    ui.mic()?.click();
    await settle();
    ui.box.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    await settle();
    expect(ui.mic()?.getAttribute("aria-pressed")).toBe("false");
    expect(transcribe).not.toHaveBeenCalled();
    expect(outer).not.toHaveBeenCalled();
    // With nothing to cancel, Escape passes through untouched.
    ui.box.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    expect(outer).toHaveBeenCalledTimes(1);
    window.removeEventListener("keydown", outer);
    void unmount(ui.comp);
  });
});

describe("VoiceInput presets", () => {
  it("shows a failed listing instead of going quiet, then recovers on the retry", async () => {
    vi.useFakeTimers();
    const presets = vi
      .spyOn(voiceApi, "presets")
      .mockRejectedValueOnce(new Error("server restarting"))
      .mockResolvedValue(ONE);
    const ui = composer(take());
    await settle();
    expect(ui.mic()?.disabled).toBe(true);
    expect(voicePresets.error).toBe("server restarting");
    expect(ui.row.querySelector(".bg-red")).not.toBeNull();
    await vi.advanceTimersByTimeAsync(RETRY_BASE_MS);
    await settle();
    expect(presets).toHaveBeenCalledTimes(2);
    expect(ui.mic()?.disabled).toBe(false);
    expect(ui.row.querySelector(".bg-red")).toBeNull();
    void unmount(ui.comp);
  });

  it("refetches on reconnect, so presets added by a restart reach an open tab", async () => {
    const presets = vi.spyOn(voiceApi, "presets").mockResolvedValue({
      default: "a",
      presets: [{ name: "a", kind: "command", available: false, reason: "not installed" }],
    });
    const ui = composer(take());
    await settle();
    expect(ui.mic()?.disabled).toBe(true);
    presets.mockResolvedValue({
      default: "openai",
      presets: [{ name: "openai", kind: "openai-compatible", available: true }],
    });
    session.acceptHandshake(session.version ?? "1.0.0", null, session.handle ?? "me");
    await settle();
    expect(presets).toHaveBeenCalledTimes(2);
    expect(ui.mic()?.disabled).toBe(false);
    void unmount(ui.comp);
  });
});
