import { mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import HandsFreeInput from "./HandsFreeInput.svelte";
import { room } from "../../state/room.svelte.js";
import { draft } from "../../state/draft.svelte.js";
import { voicePresets } from "../../state/voice-presets.svelte.js";
import { handsFree, HandsFreePreferences } from "../../state/hands-free.svelte.js";
import { voiceApi } from "../../lib/voice-api";
import { saveMic } from "../../lib/mic-device";
import { FakeVad } from "../../lib/vad-fakes";
import { fakeAudioContext, fakeMicStream } from "../../lib/mic-fakes";
import type { ListenerSources } from "../../lib/voice-listener";
import type { Attachment } from "../../lib/contracts";
const conversation = {
  id: "voice-line",
  name: "voice",
  topic: "",
  created_at: 1,
  archived_at: null,
  live_count: 1,
};
const attachment: Attachment = {
  id: "worker",
  conv_id: "voice-line",
  name: "sol",
  adapter: "fake",
  command: ["fake"],
  cwd: "/tmp",
  status: "running",
  last_seen: 0,
  created_at: 1,
  cli_session: null,
  cwd_git: null,
};
async function settle(): Promise<void> {
  for (let i = 0; i < 30; i++) await tick();
}
const button = () => document.querySelector<HTMLButtonElement>("button.hands-free");

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("isSecureContext", true);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: {} });
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
  handsFree.update({ enabled: false, pauseMs: 1400, hiddenMs: 10000 });
  room.conversation = conversation;
  room.attachments = [attachment];
  draft.openLine(conversation.id);
  draft.text = "an unrelated draft";
  voicePresets.listing = { default: "asr", presets: [{ name: "asr", kind: "command", available: true }] };
  voicePresets.choose("asr");
});
afterEach(() => {
  handsFree.update({ enabled: false, pauseMs: 1400, hiddenMs: 60000 });
  voicePresets.reset();
  voicePresets.choose(null);
  room.leave({ clearRoute: false });
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  localStorage.clear();
  document.body.replaceChildren();
});
async function setup() {
  const mics: ReturnType<typeof fakeMicStream>[] = [];
  const vads: FakeVad[] = [];
  const sources: ListenerSources = {
    createContext: fakeAudioContext,
    micDeviceId: () => "selected",
    getUserMedia: vi.fn(() => {
      const mic = fakeMicStream();
      mics.push(mic);
      return Promise.resolve(mic.stream);
    }),
    createVad: vi.fn((options: Parameters<ListenerSources["createVad"]>[0]) => {
      const vad = new FakeVad(options);
      vads.push(vad);
      return Promise.resolve(vad);
    }),
  };
  const component = mount(HandsFreeInput, { target: document.body, props: { sources } });
  await settle();
  return { component, mics, vads, sources };
}
async function speak(vad: FakeVad | undefined) {
  if (!vad) throw new Error("no VAD");
  await vad.frames(0.99, 20);
  await vad.frames(0, 50);
  await settle();
}
describe("hands-free composer", () => {
  it("starts in one click, sends with the selected preset, displays sent text and preserves the draft", async () => {
    const say = vi.spyOn(room, "say").mockResolvedValue(true);
    const transcribe = vi
      .spyOn(voiceApi, "transcribe")
      .mockResolvedValue({ text: "open the menu", language: "en", duration: 1, segments: [] });
    const s = await setup();
    button()?.click();
    await settle();
    expect(button()?.getAttribute("aria-pressed")).toBe("true");
    expect(new HandsFreePreferences().value.enabled).toBe(true);
    expect(document.body.textContent).toContain("listening");
    await speak(s.vads[0]);
    expect(transcribe).toHaveBeenCalledWith("voice-line", expect.any(Blob), "asr", expect.any(AbortSignal));
    expect(say).toHaveBeenCalledExactlyOnceWith("open the menu");
    expect(document.body.textContent).toContain("Voice sent: open the menu");
    expect(draft.text).toBe("an unrelated draft");
    button()?.click();
    await settle();
    expect(s.mics[0]?.stop).toHaveBeenCalledOnce();
    expect(new HandsFreePreferences().value.enabled).toBe(false);
    await unmount(s.component);
  });

  it("is an icon button whose label and badge follow the state, with errors and sends floating above", async () => {
    vi.spyOn(room, "say").mockResolvedValue(true);
    vi.spyOn(voiceApi, "transcribe").mockResolvedValue({
      text: "next slide",
      language: "en",
      duration: 1,
      segments: [],
    });
    const s = await setup();
    expect(button()?.textContent.trim()).toBe("");
    expect(button()?.getAttribute("aria-label")).toBe("Hands-free: off — click to listen and send by voice");
    button()?.click();
    await settle();
    expect(button()?.getAttribute("aria-label")).toBe("Hands-free: listening — click to turn off");
    expect(button()?.textContent).toContain("listening");
    expect(button()?.querySelector("[data-hands-free-dot]")?.className).toContain("animate-pulse");
    await speak(s.vads[0]);
    const bubble = document.querySelector('[aria-live="polite"]')?.parentElement;
    expect(bubble?.className).toContain("absolute");
    expect(bubble?.textContent).toContain("Voice sent: next slide");
    await vi.advanceTimersByTimeAsync(8000);
    await settle();
    expect(document.body.textContent).not.toContain("Voice sent");
    await unmount(s.component);
  });

  it("explains in its label why it is unavailable", async () => {
    voicePresets.listing = { default: "", presets: [] };
    voicePresets.choose(null);
    const s = await setup();
    expect(button()?.disabled).toBe(true);
    expect(button()?.getAttribute("aria-label")).toBe("Hands-free: off — No speech recognizer is available.");
    await unmount(s.component);
  });

  it("releases a hidden mic on the configured fake timeout and resumes without interaction", async () => {
    handsFree.update({ enabled: true });
    const s = await setup();
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(9999);
    expect(s.mics[0]?.stop).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await settle();
    expect(s.mics[0]?.stop).toHaveBeenCalledOnce();
    expect(document.body.textContent).toContain("paused while tab is hidden");
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    document.dispatchEvent(new Event("visibilitychange"));
    await settle();
    expect(s.mics).toHaveLength(2);
    expect(document.body.textContent).toContain("listening");
    await unmount(s.component);
    expect(s.mics[1]?.stop).toHaveBeenCalledOnce();
  });

  it("reopens on a mic selection or pause change, and aborts late transcripts on line changes", async () => {
    handsFree.update({ enabled: true });
    const say = vi.spyOn(room, "say").mockResolvedValue(true);
    let finish!: (value: Awaited<ReturnType<typeof voiceApi.transcribe>>) => void;
    const transcribe = vi.spyOn(voiceApi, "transcribe").mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const s = await setup();
    saveMic("other");
    await settle();
    expect(s.mics[0]?.stop).toHaveBeenCalledOnce();
    expect(s.mics).toHaveLength(2);
    handsFree.update({ pauseMs: 1500 });
    await settle();
    expect(s.vads[2]?.options.redemptionMs).toBe(1500);
    await speak(s.vads[2]);
    const signal = transcribe.mock.calls[0]?.[3];
    room.conversation = { ...conversation, id: "another-line" };
    await settle();
    expect(signal?.aborted).toBe(true);
    finish({ text: "old instruction", language: "en", duration: 1, segments: [] });
    await settle();
    expect(say).not.toHaveBeenCalled();
    expect(s.mics[2]?.stop).toHaveBeenCalledOnce();
    await unmount(s.component);
  });

  it("keeps the off toggle usable if the server stops offering recognizers", async () => {
    handsFree.update({ enabled: true });
    const s = await setup();
    voicePresets.listing = { default: "asr", presets: [] };
    await settle();
    expect(button()?.disabled).toBe(false);
    expect(s.mics[0]?.stop).toHaveBeenCalledOnce();
    button()?.click();
    await settle();
    expect(handsFree.value.enabled).toBe(false);
    await unmount(s.component);
  });
});
