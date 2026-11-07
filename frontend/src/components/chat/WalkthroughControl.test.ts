import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import WalkthroughControl from "./WalkthroughControl.svelte";
import { screenApi } from "../../lib/screen-api";
import { voiceApi } from "../../lib/voice-api";
import { walkthroughApi } from "../../lib/walkthrough-api";
import type { RecorderSources } from "../../lib/voice-recorder";
import { FakeAudioContext, fakeAudioContext } from "../../lib/mic-fakes";
import { room } from "../../state/room.svelte.js";
import { draft } from "../../state/draft.svelte.js";
import { voicePresets } from "../../state/voice-presets.svelte.js";
import { walkthrough } from "../../state/walkthrough.svelte.js";

const line = { id: "l", name: "L", topic: "", created_at: 1, archived_at: null, live_count: 0 };
const region = { x: 0, y: 0, width: 100, height: 100 };
const share = { share_id: "s", handle: "alice", device_name: "Desk", status: "active" as const, region };

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i++) await tick();
}
function button(text: string): HTMLButtonElement | undefined {
  return [...document.querySelectorAll("button")].find((item) => item.textContent.includes(text));
}
function sources(): RecorderSources {
  const stream = { getTracks: () => [{ stop: vi.fn(), label: "Headset (Jabra)" }] } as unknown as MediaStream;
  return {
    getUserMedia: () => Promise.resolve(stream),
    isTypeSupported: () => true,
    createRecorder: () => {
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
          recorder.ondataavailable?.({ data: new Blob(["audio"]) });
          recorder.onstop?.();
        },
      };
      return recorder as unknown as MediaRecorder;
    },
  };
}
function setup(extra: Partial<RecorderSources> = {}) {
  room.conversation = line;
  room.screenShare = null;
  draft.openLine(line.id);
  draft.clear();
  walkthrough.last = { line: "l", device: "d", region };
  vi.spyOn(screenApi, "devices").mockResolvedValue({
    devices: [{ id: "d", name: "Desk", os: "test", online: true, monitors: [] }],
  });
  vi.spyOn(screenApi, "start").mockResolvedValue({ share_id: "s", status: "waiting" });
  vi.spyOn(screenApi, "current").mockResolvedValue({ share });
  vi.spyOn(walkthroughApi, "arm").mockResolvedValue({ ok: true });
  vi.spyOn(walkthroughApi, "stop").mockResolvedValue({ ok: true });
  vi.spyOn(walkthroughApi, "cancel").mockResolvedValue({ ok: true });
  vi.spyOn(voiceApi, "presets").mockResolvedValue({
    default: "fake",
    presets: [{ name: "fake", kind: "fake", available: true }],
  });
  vi.spyOn(voiceApi, "transcribe").mockResolvedValue({
    text: "click",
    duration: 1,
    language: "en",
    segments: [{ start: 0, end: 1, text: "click" }],
  });
  return mount(WalkthroughControl, { target: document.body, props: { sources: { ...sources(), ...extra } } });
}

afterEach(() => {
  voicePresets.reset();
  vi.restoreAllMocks();
  room.leave({ clearRoute: false });
  walkthrough.last = null;
  draft.text = "";
  document.body.replaceChildren();
});

describe("walkthrough control", () => {
  it("shows the mic level, its name and the no-input hint while recording, and frees the audio", async () => {
    vi.useFakeTimers();
    try {
      FakeAudioContext.made = [];
      const component = setup({ createAudioContext: fakeAudioContext });
      await settle();
      button("Show me")?.click();
      await settle();
      const context = FakeAudioContext.last();
      context.analyser.amplitude = 0.05;
      vi.advanceTimersByTime(100);
      await tick();
      const meter = document.querySelector('[role="meter"]');
      expect(meter?.getAttribute("aria-valuenow")).toBe("30");
      expect(document.body.textContent).toContain("Mic: Headset (Jabra)");
      expect(document.querySelector('[role="alert"]')).toBeNull();
      context.analyser.amplitude = 0;
      vi.advanceTimersByTime(3000);
      await tick();
      expect(document.querySelector('[role="alert"]')?.textContent).toContain("no input detected");
      button("Cancel")?.click();
      await settle();
      expect(context.closed).toBe(true);
      await unmount(component);
    } finally {
      vi.useRealTimers();
    }
  });

  it("allows a walkthrough after an ordinary share is declined", async () => {
    const component = setup();
    await settle();
    room.screenShare = { ...share, share_id: "previous", status: "waiting" };
    await tick();
    expect(button("Show me")?.disabled).toBe(true);
    room.screenShare = { ...share, share_id: "previous", status: "declined" };
    await tick();
    expect(button("Show me")?.disabled).toBe(false);
    button("Show me")?.click();
    await settle();
    expect(screenApi.start).toHaveBeenCalledWith("l", "d", region, true);
    expect(button("Stop and send")).toBeDefined();
    await unmount(component);
  });

  it("starts the remembered share, records and sends notes with transcript", async () => {
    const finish = vi.spyOn(walkthroughApi, "finish").mockResolvedValue({ message: { id: 1 } });
    const component = setup();
    await settle();
    button("Show me")?.click();
    await settle();
    expect(button("Stop and send")).toBeDefined();
    expect(screenApi.start).toHaveBeenCalledWith("l", "d", region, true);
    expect(walkthroughApi.arm).toHaveBeenCalledOnce();
    draft.text = "notes";
    button("Stop and send")?.click();
    await settle();
    expect(finish).toHaveBeenCalledWith("l", "s", {
      notes: "notes",
      segments: [{ start: 0, end: 1, text: "click" }],
      transcription_error: false,
      mark_pointer: false,
    });
    expect(draft.text).toBe("");
    await unmount(component);
  });

  it("Escape discards the take and releases the share", async () => {
    const finish = vi.spyOn(walkthroughApi, "finish");
    const component = setup();
    await settle();
    draft.text = "existing";
    button("Show me")?.click();
    await settle();
    draft.text = "private notes";
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await settle();
    expect(walkthroughApi.cancel).toHaveBeenCalledWith("l", "s");
    expect(draft.text).toBe("existing");
    expect(finish).not.toHaveBeenCalled();
    await unmount(component);
  });

  it("sends the frames with an explanation when recognition fails", async () => {
    const finish = vi.spyOn(walkthroughApi, "finish").mockResolvedValue({ message: { id: 2 } });
    const component = setup();
    vi.mocked(voiceApi.transcribe).mockRejectedValue(new Error("recognizer failed"));
    await settle();
    button("Show me")?.click();
    await settle();
    button("Stop and send")?.click();
    await settle();
    expect(finish).toHaveBeenCalledWith("l", "s", {
      notes: "",
      segments: [],
      transcription_error: true,
      mark_pointer: false,
    });
    await unmount(component);
  });

  it("releases a take when the helper disconnects before recording starts", async () => {
    const component = setup();
    vi.mocked(screenApi.current).mockResolvedValue({ share: null });
    await settle();
    button("Show me")?.click();
    await settle();
    expect(walkthroughApi.cancel).toHaveBeenCalledWith("l", "s");
    expect(document.body.textContent).toContain("Screen sharing ended before recording began.");
    await unmount(component);
  });
});
