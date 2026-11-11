import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import WalkthroughControl from "./WalkthroughControl.svelte";
import ScreenControls from "./ScreenControls.svelte";
import { screenApi } from "../../lib/screen-api";
import { walkthroughApi } from "../../lib/walkthrough-api";
import type { RecorderSources } from "../../lib/voice-recorder";
import { FakeAudioContext, fakeAudioContext } from "../../lib/mic-fakes";
import { layout } from "../../state/layout.svelte.js";
import { room } from "../../state/room.svelte.js";
import { screenStatus } from "../../state/screen-status.svelte.js";
import { draft } from "../../state/draft.svelte.js";
import { voicePresets } from "../../state/voice-presets.svelte.js";
import { walkthrough } from "../../state/walkthrough.svelte.js";
import { sendFailures } from "../../state/send-failures.svelte.js";
import type { Transcript } from "../../lib/voice-api";

const line = { id: "l", name: "L", topic: "", created_at: 1, archived_at: null, live_count: 0 };
const other = { ...line, id: "b", name: "B" };
const region = { x: 0, y: 0, width: 100, height: 100 };
const share = { share_id: "s", handle: "alice", device_name: "Desk", status: "active" as const, region };

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i++) await tick();
}
function button(text: string): HTMLButtonElement | undefined {
  return [...document.querySelectorAll("button")].find(
    (item) => item.textContent.includes(text) || item.getAttribute("aria-label")?.startsWith(text),
  );
}
async function startWalkthrough(): Promise<void> {
  button("Screen:")?.click();
  await tick();
  button("Share screen + record voice")?.click();
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
  screenStatus.devices = [{ id: "d", name: "Desk", os: "test", online: true, monitors: [] }];
  vi.spyOn(screenApi, "start").mockResolvedValue({ share_id: "s", status: "waiting" });
  vi.spyOn(screenApi, "current").mockResolvedValue({ share });
  vi.spyOn(walkthroughApi, "arm").mockResolvedValue({ ok: true });
  vi.spyOn(walkthroughApi, "stop").mockResolvedValue({ ok: true });
  vi.spyOn(walkthroughApi, "cancel").mockResolvedValue({ ok: true });
  voicePresets.listing = {
    default: "fake",
    presets: [{ name: "fake", kind: "fake", available: true }],
  };
  vi.spyOn(walkthroughApi, "transcribe").mockResolvedValue({
    text: "click",
    duration: 1,
    language: "en",
    segments: [{ start: 0, end: 1, text: "click" }],
  });
  return mount(WalkthroughControl, { target: document.body, props: { sources: { ...sources(), ...extra } } });
}

afterEach(() => {
  layout.narrow = false;
  voicePresets.reset();
  vi.restoreAllMocks();
  screenStatus.devices = [];
  room.leave({ clearRoute: false });
  sendFailures.discard("l");
  sendFailures.discard("b");
  walkthrough.last = null;
  draft.text = "";
  document.body.replaceChildren();
});

describe("walkthrough control on a phone", () => {
  it("does not offer Show me when narrow, and offers it again when wide", async () => {
    layout.narrow = true;
    const component = setup();
    await settle();
    expect(button("Screen:")).toBeUndefined();
    expect(document.querySelector('[aria-label="Walkthrough"]')).toBeNull();
    layout.narrow = false;
    await settle();
    expect(button("Screen:")).toBeDefined();
    await unmount(component);
  });

  it("keeps the controls of a take already under way so it can be cancelled", async () => {
    const component = setup();
    await settle();
    await startWalkthrough();
    await settle();
    layout.narrow = true;
    await settle();
    expect(button("Cancel")).toBeDefined();
    button("Cancel")?.click();
    await settle();
    expect(document.querySelector('[aria-label="Walkthrough"]')).toBeNull();
    await unmount(component);
  });
});

describe("walkthrough control", () => {
  it("keeps voice recording through first-time monitor selection and sends the transcript", async () => {
    const finish = vi.spyOn(walkthroughApi, "finish").mockResolvedValue({ message: { id: 3 } });
    const component = setup();
    walkthrough.last = null;
    vi.mocked(screenApi.current).mockResolvedValue({ share: null });
    screenStatus.devices = [
      {
        id: "d",
        name: "Desk",
        os: "test",
        online: true,
        monitors: [{ id: 1, ...region, scale: 1, primary: true }],
      },
    ];
    vi.spyOn(screenApi, "preview").mockResolvedValue({
      out_width: 100,
      out_height: 100,
      mime: "image/png",
      data: "preview",
    });
    const picker = mount(ScreenControls, { target: document.body });
    await settle();
    await startWalkthrough();
    await settle();
    expect(walkthrough.selecting).toBe(true);
    expect(screenApi.start).not.toHaveBeenCalled();
    button("Desk (online)")?.click();
    await settle();
    button("1 (100 × 100)")?.click();
    await settle();
    vi.mocked(screenApi.current).mockResolvedValue({ share });
    button("Share screen")?.click();
    await settle();
    expect(screenApi.start).toHaveBeenCalledExactlyOnceWith("l", "d", region, true);
    expect(walkthroughApi.arm).toHaveBeenCalledExactlyOnceWith("l", "s");
    button("Stop and send")?.click();
    await settle();
    expect(walkthroughApi.transcribe).toHaveBeenCalledOnce();
    expect(finish).toHaveBeenCalledWith(
      "l",
      "s",
      expect.objectContaining({
        segments: [{ start: 0, end: 1, text: "click" }],
        transcription_error: false,
      }),
    );
    await unmount(component);
    await unmount(picker);
  });

  it("shows the mic level, its name and the no-input hint while recording, and frees the audio", async () => {
    vi.useFakeTimers();
    try {
      FakeAudioContext.made = [];
      const component = setup({ createAudioContext: fakeAudioContext });
      await settle();
      await startWalkthrough();
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
    button("Screen:")?.click();
    await tick();
    expect(button("Share screen + record voice")?.getAttribute("aria-disabled")).toBe("true");
    room.screenShare = { ...share, share_id: "previous", status: "declined" };
    await tick();
    expect(button("Share screen + record voice")?.getAttribute("aria-disabled")).toBe("false");
    button("Share screen + record voice")?.click();
    await settle();
    expect(screenApi.start).toHaveBeenCalledWith("l", "d", region, true);
    expect(button("Stop and send")).toBeDefined();
    await unmount(component);
  });

  it("starts the remembered share, records and sends notes with transcript", async () => {
    const finish = vi.spyOn(walkthroughApi, "finish").mockResolvedValue({ message: { id: 1 } });
    const component = setup();
    await settle();
    await startWalkthrough();
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
      transcript_text: "",
      transcription_error: false,
      no_input: false,
      duration_ms: 0,
      mark_pointer: false,
    });
    expect(draft.text).toBe("");
    await unmount(component);
  });

  it("sends recovered utterance timestamps from walkthrough transcription", async () => {
    const finish = vi.spyOn(walkthroughApi, "finish").mockResolvedValue({ message: { id: 1 } });
    const component = setup();
    vi.mocked(walkthroughApi.transcribe).mockResolvedValue({
      text: "click the gear",
      duration: 0,
      language: "en",
      segments: [
        { start: 1.2, end: 2, text: "click", utterance: true },
        { start: 4, end: 5, text: "the gear", utterance: true },
      ],
    });
    await settle();
    await startWalkthrough();
    await settle();
    button("Stop and send")?.click();
    await settle();
    expect(finish).toHaveBeenCalledWith(
      "l",
      "s",
      expect.objectContaining({
        segments: [
          { start: 1.2, end: 2, text: "click", utterance: true },
          { start: 4, end: 5, text: "the gear", utterance: true },
        ],
        transcript_text: "",
        transcription_error: false,
      }),
    );
    await unmount(component);
  });

  it("Escape discards the take and releases the share", async () => {
    const finish = vi.spyOn(walkthroughApi, "finish");
    const component = setup();
    await settle();
    draft.text = "existing";
    await startWalkthrough();
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
    vi.mocked(walkthroughApi.transcribe).mockRejectedValue(new Error("recognizer failed"));
    await settle();
    await startWalkthrough();
    await settle();
    button("Stop and send")?.click();
    await settle();
    expect(finish).toHaveBeenCalledWith("l", "s", {
      notes: "",
      segments: [],
      transcript_text: "",
      transcription_error: true,
      no_input: false,
      duration_ms: 0,
      mark_pointer: false,
    });
    await unmount(component);
  });

  it("releases a take when the helper disconnects before recording starts", async () => {
    const component = setup();
    vi.mocked(screenApi.current).mockResolvedValue({ share: null });
    await settle();
    await startWalkthrough();
    await settle();
    expect(walkthroughApi.cancel).toHaveBeenCalledWith("l", "s");
    expect(document.body.textContent).toContain("Screen sharing ended before recording began.");
    await unmount(component);
  });
});

describe("a take in flight belongs to its own line", () => {
  const transcript: Transcript = { text: "", duration: 1, language: "en", segments: [] };
  /** Finish a walkthrough on line L, leaving its transcription pending, then start one on line B. */
  async function finishThenStartElsewhere(): Promise<(value: Transcript) => void> {
    let resolve: (value: Transcript) => void = () => undefined;
    vi.mocked(walkthroughApi.transcribe).mockReturnValue(
      new Promise<Transcript>((done) => {
        resolve = done;
      }),
    );
    await settle();
    await startWalkthrough();
    await settle();
    button("Stop and send")?.click();
    await settle();
    expect(walkthroughApi.transcribe).toHaveBeenCalledOnce();
    walkthrough.last = { line: "b", device: "d", region };
    vi.mocked(screenApi.start).mockResolvedValue({ share_id: "s2", status: "waiting" });
    vi.mocked(screenApi.current).mockResolvedValue({ share: { ...share, share_id: "s2" } });
    room.conversation = other;
    room.screenShare = null;
    await settle();
    await startWalkthrough();
    await settle();
    expect(screenApi.start).toHaveBeenLastCalledWith("b", "d", region, true);
    return resolve;
  }

  it("posts the take to its line when another walkthrough began meanwhile", async () => {
    const finish = vi.spyOn(walkthroughApi, "finish").mockResolvedValue({ message: { id: 1 } });
    const component = setup();
    const resolve = await finishThenStartElsewhere();
    resolve({ ...transcript, segments: [{ start: 0, end: 1, text: "click" }] });
    await settle();
    expect(finish).toHaveBeenCalledExactlyOnceWith(
      "l",
      "s",
      expect.objectContaining({ segments: [{ start: 0, end: 1, text: "click" }] }),
    );
    expect(walkthroughApi.cancel).not.toHaveBeenCalledWith("l", "s");
    expect(button("Stop and send")).toBeDefined();
    expect(walkthrough.line).toBe("b");
    expect(walkthrough.shareId).toBe("s2");
    await unmount(component);
  });

  it("keeps a take refused after the person left held for retry on its own line", async () => {
    const finish = vi.spyOn(walkthroughApi, "finish").mockRejectedValue(new Error("refused"));
    const component = setup();
    const resolve = await finishThenStartElsewhere();
    resolve(transcript);
    await settle();
    expect(finish).toHaveBeenCalledOnce();
    expect(sendFailures.get("b")).toBeUndefined();
    expect(sendFailures.get("l")?.take?.share).toBe("s");
    expect(button("Stop and send")).toBeDefined();
    finish.mockResolvedValue({ message: { id: 2 } });
    button("Cancel")?.click();
    await settle();
    room.conversation = line;
    await settle();
    button("retry")?.click();
    await settle();
    expect(finish).toHaveBeenLastCalledWith("l", "s", expect.anything());
    expect(sendFailures.get("l")).toBeUndefined();
    await unmount(component);
  });

  it("drops a take the person cancels and releases its share", async () => {
    const finish = vi.spyOn(walkthroughApi, "finish").mockResolvedValue({ message: { id: 1 } });
    const component = setup();
    let resolve: (value: Transcript) => void = () => undefined;
    vi.mocked(walkthroughApi.transcribe).mockReturnValue(
      new Promise<Transcript>((done) => {
        resolve = done;
      }),
    );
    await settle();
    await startWalkthrough();
    await settle();
    button("Stop and send")?.click();
    await settle();
    expect(walkthroughApi.transcribe).toHaveBeenCalledOnce();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await settle();
    expect(walkthroughApi.cancel).toHaveBeenCalledWith("l", "s");
    resolve(transcript);
    await settle();
    expect(finish).not.toHaveBeenCalled();
    expect(sendFailures.get("l")).toBeUndefined();
    await unmount(component);
  });

  it("does not hold a take the person cancelled while it was being sent", async () => {
    let refuse: (error: Error) => void = () => undefined;
    const finish = vi.spyOn(walkthroughApi, "finish").mockReturnValue(
      new Promise((_, reject) => {
        refuse = reject;
      }),
    );
    const component = setup();
    await settle();
    await startWalkthrough();
    await settle();
    button("Stop and send")?.click();
    await settle();
    expect(finish).toHaveBeenCalledOnce();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await settle();
    expect(walkthroughApi.cancel).toHaveBeenCalledWith("l", "s");
    refuse(new Error("share cancelled"));
    await settle();
    expect(sendFailures.get("l")).toBeUndefined();
    await unmount(component);
  });
});
