import { afterEach, describe, expect, it, vi } from "vitest";
import { RETRY_BASE_MS, RETRY_MAX_MS, VoicePresets, retryDelay } from "./voice-presets.svelte.js";
import { voiceApi } from "../lib/voice-api";
import type { VoiceListing } from "../lib/voice-api";

const LISTING: VoiceListing = {
  default: "a",
  presets: [
    { name: "a", kind: "command", available: true },
    { name: "b", kind: "command", available: true },
  ],
};

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("voice presets store", () => {
  it("backs off exponentially up to a cap", () => {
    expect(retryDelay(0)).toBe(RETRY_BASE_MS);
    expect(retryDelay(1)).toBe(2 * RETRY_BASE_MS);
    expect(retryDelay(3)).toBe(8 * RETRY_BASE_MS);
    expect(retryDelay(40)).toBe(RETRY_MAX_MS);
  });

  it("retries a failed load with growing delays until it succeeds", async () => {
    vi.useFakeTimers();
    const presets = vi
      .spyOn(voiceApi, "presets")
      .mockRejectedValueOnce(new Error("down"))
      .mockRejectedValueOnce(new Error("still down"))
      .mockResolvedValue(LISTING);
    const store = new VoicePresets();
    store.ensure();
    await vi.advanceTimersByTimeAsync(0);
    expect(store.error).toBe("down");
    await vi.advanceTimersByTimeAsync(RETRY_BASE_MS);
    expect(store.error).toBe("still down");
    expect(presets).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(2 * RETRY_BASE_MS - 1);
    expect(presets).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(store.listing).toEqual(LISTING);
    expect(store.error).toBeNull();
    store.reset();
  });

  it("lets the newest load win and only refreshes once something wanted the list", async () => {
    let first: (value: VoiceListing) => void = () => undefined;
    const presets = vi
      .spyOn(voiceApi, "presets")
      .mockImplementationOnce(() => new Promise((resolve) => (first = resolve)))
      .mockResolvedValue(LISTING);
    const store = new VoicePresets();
    store.refresh();
    expect(presets).not.toHaveBeenCalled();
    store.ensure();
    store.refresh();
    await Promise.resolve();
    first({ default: "stale", presets: [] });
    for (let turn = 0; turn < 10; turn++) await Promise.resolve();
    expect(store.listing?.default).toBe("a");
  });

  it("remembers this browser's pick and falls back when it cannot run", () => {
    const store = new VoicePresets();
    store.listing = LISTING;
    expect(store.active).toBe("a");
    store.choose("b");
    expect(new VoicePresets().chosen).toBe("b");
    expect(store.active).toBe("b");
    store.markUnavailable("b", "503");
    expect(store.active).toBe("a");
    store.choose(null);
    expect(new VoicePresets().chosen).toBeNull();
    store.reset();
    expect(store.active).toBeNull();
    store.markUnavailable("a", "ignored without a listing");
  });
});
