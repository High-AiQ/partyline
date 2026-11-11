import { mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VoiceInput from "./VoiceInput.svelte";
import { room } from "../../state/room.svelte.js";
import { draft } from "../../state/draft.svelte.js";
import { voicePresets } from "../../state/voice-presets.svelte.js";
import { voiceApi } from "../../lib/voice-api";
import type { Transcript, VoiceListing } from "../../lib/voice-api";
import type { RecorderSources } from "../../lib/voice-recorder";

const conversation = { id: "l", name: "L", topic: "", created_at: 1, archived_at: null, live_count: 0 };
const ONE: VoiceListing = { default: "a", presets: [{ name: "a", kind: "command", available: true }] };

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i++) await tick();
}

function take(): RecorderSources {
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

function mounted() {
  const row = document.body.appendChild(document.createElement("div"));
  const box = row.appendChild(document.createElement("textarea"));
  const comp = mount(VoiceInput, {
    target: row,
    props: { box, oninserted: () => undefined, sources: take() },
  });
  return {
    comp,
    row,
    mic: () => row.querySelector<HTMLButtonElement>("button.voice"),
    discard: () => row.querySelector<HTMLButtonElement>('button[aria-label="Discard recording"]'),
  };
}

beforeEach(() => {
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal("MediaRecorder", { isTypeSupported: () => true });
  Object.defineProperty(navigator, "mediaDevices", { value: {}, configurable: true });
  room.conversation = conversation;
  draft.openLine(conversation.id);
  draft.text = "";
  voicePresets.listing = ONE;
});

afterEach(() => {
  voicePresets.reset();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  room.leave({ clearRoute: false });
  draft.text = "";
  document.body.replaceChildren();
});

describe("VoiceInput labels and states", () => {
  it("says what the gain button does while recording, and keeps the meter and tooltip", async () => {
    const ui = mounted();
    await settle();
    expect(ui.mic()?.textContent).not.toContain("Click to transcribe");
    ui.mic()?.click();
    await settle();
    const text = ui.mic()?.textContent ?? "";
    expect(text).toContain("Click to transcribe");
    expect(text).toContain("Transcribe");
    expect(text).not.toContain("send");
    expect(ui.mic()?.getAttribute("aria-label")).toBe("stop recording");
    void unmount(ui.comp);
  });

  it("makes discard a small, quiet ✕ and not the word cancel", async () => {
    const ui = mounted();
    await settle();
    ui.mic()?.click();
    await settle();
    const discard = ui.discard();
    expect(discard?.textContent.trim()).toBe("✕");
    expect(discard?.className).toContain("h-8");
    expect(discard?.className).toContain("opacity-70");
    expect(ui.row.textContent).not.toMatch(/cancel/i);
    void unmount(ui.comp);
  });

  it("shows Transcribing… until the text lands, then inserts it", async () => {
    let finish: (t: Transcript) => void = () => undefined;
    vi.spyOn(voiceApi, "transcribe").mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const ui = mounted();
    await settle();
    ui.mic()?.click();
    await settle();
    ui.mic()?.click();
    await settle();
    expect(ui.mic()?.textContent).toContain("Transcribing…");
    expect(ui.mic()?.textContent).not.toContain("Click to transcribe");
    expect(ui.row.querySelector('[role="status"]')?.textContent).toBe("transcribing");
    finish({ text: "hello", language: "en", duration: 1, segments: [] });
    await settle();
    expect(draft.text).toBe("hello");
    expect(ui.mic()?.textContent).not.toContain("Transcribing");
    void unmount(ui.comp);
  });

  it("says Heard nothing for an empty transcript instead of going quiet", async () => {
    vi.spyOn(voiceApi, "transcribe").mockResolvedValue({
      text: "  ",
      language: "en",
      duration: 1,
      segments: [],
    });
    const ui = mounted();
    await settle();
    ui.mic()?.click();
    await settle();
    ui.mic()?.click();
    await settle();
    expect(room.notice).toEqual({ message: "Heard nothing", kind: "error" });
    expect(draft.text).toBe("");
    void unmount(ui.comp);
  });

  it("shows the error when the transcription fails", async () => {
    vi.spyOn(voiceApi, "transcribe").mockRejectedValue(new Error("recognizer is down"));
    const ui = mounted();
    await settle();
    ui.mic()?.click();
    await settle();
    ui.mic()?.click();
    await settle();
    expect(room.notice).toEqual({ message: "recognizer is down", kind: "error" });
    expect(ui.mic()?.textContent).not.toContain("Transcribing");
    void unmount(ui.comp);
  });
});
