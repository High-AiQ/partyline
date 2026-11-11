/**
 * A hidden tab keeps its drafts but nothing live: a test take stops when Voice
 * is hidden, and the Voice listing retries on its own after a failure.
 */
import { flushSync, mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import SettingsDialog from "../dialogs/SettingsDialog.svelte";
import VoiceSection from "./sections/VoiceSection.svelte";
import { asrApi } from "../../lib/asr-api";
import type { AsrSettings } from "../../lib/asr-api";
import { voiceApi } from "../../lib/voice-api";
import { MAX_TAKE_MS } from "../../lib/voice";
import * as settingsApi from "../../lib/settings-api";
import { settingsNav } from "../../state/settings-nav.svelte.js";
import { voicePresets } from "../../state/voice-presets.svelte.js";

const listing: AsrSettings = {
  default: "cloud",
  presets: [
    {
      name: "cloud",
      kind: "openai-compatible",
      source: "database",
      editable: true,
      overrides_config: false,
      is_default: true,
      can_be_default: true,
      available: true,
      fields: { base_url: "https://speech.example.test", model: "whisper-large-v3" },
    },
  ],
};
let mounted: ReturnType<typeof mount> | null = null;
async function settle(): Promise<void> {
  for (let i = 0; i < 25; i++) await tick();
}
function clickText(text: string): void {
  const button = [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent.trim() === text,
  );
  if (!button) throw new Error(`missing button ${text}`);
  button.click();
  flushSync();
}
beforeEach(() => {
  vi.useFakeTimers();
  Object.defineProperty(Element.prototype, "scrollIntoView", { value: vi.fn(), configurable: true });
  Object.defineProperty(Element.prototype, "scrollTo", { value: vi.fn(), configurable: true });
});
afterEach(async () => {
  if (mounted) await unmount(mounted);
  mounted = null;
  settingsNav.close();
  voicePresets.reset();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  document.body.replaceChildren();
});

it("waits for a pushed settings snapshot without retry-fetching", async () => {
  const list = vi.spyOn(asrApi, "list");
  const mic = vi.spyOn(voiceApi, "presets");
  mounted = mount(VoiceSection, { target: document.body });
  await vi.advanceTimersByTimeAsync(60_000);
  expect(list).not.toHaveBeenCalled();
  expect(mic).not.toHaveBeenCalled();
  voicePresets.receive(listing);
  await settle();
  expect(document.querySelector('[data-asr-preset="cloud"]')).not.toBeNull();
});

it("stops a test take when Voice is hidden instead of uploading hidden audio at the cap", async () => {
  const track = { stop: vi.fn() };
  class FakeRecorder {
    static isTypeSupported(): boolean {
      return true;
    }
    state = "inactive";
    mimeType = "audio/webm";
    ondataavailable: ((_event: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    onerror: (() => void) | null = null;
    start(): void {
      this.state = "recording";
    }
    stop(): void {
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob(["captured audio"]) });
      this.onstop?.();
    }
  }
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  vi.stubGlobal("isSecureContext", true);
  Object.defineProperty(navigator, "mediaDevices", {
    value: {
      getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }),
      enumerateDevices: vi.fn().mockResolvedValue([]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
    configurable: true,
  });
  vi.spyOn(settingsApi, "getGlobalProse").mockResolvedValue({ value: "saved" });
  voicePresets.receive(listing);
  const test = vi.spyOn(asrApi, "test").mockResolvedValue({
    preset: "cloud",
    text: "hidden audio",
    language: "en",
    duration: 300,
    latency_ms: 1,
  });
  settingsNav.show("voice");
  mounted = mount(SettingsDialog, { target: document.body, props: { close: vi.fn() } });
  await settle();
  clickText("test");
  await settle();
  clickText("record a test");
  await settle();
  expect(track.stop).not.toHaveBeenCalled();
  settingsNav.show("general");
  await settle();
  expect(document.querySelector("#settings-heading-general")).not.toBeNull();
  expect(track.stop).toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(MAX_TAKE_MS);
  await settle();
  expect(test).not.toHaveBeenCalled();
});

it("keeps pushed recognizers across tab switches without a fetch", async () => {
  vi.spyOn(settingsApi, "getGlobalProse").mockResolvedValue({ value: "saved" });
  const list = vi.spyOn(asrApi, "list");
  voicePresets.receive(listing);
  settingsNav.show("voice");
  mounted = mount(SettingsDialog, { target: document.body, props: { close: vi.fn() } });
  await settle();
  settingsNav.show("general");
  await settle();
  settingsNav.show("voice");
  await settle();
  expect(list).not.toHaveBeenCalled();
  expect(document.querySelector('[data-asr-preset="cloud"]')).not.toBeNull();
});
