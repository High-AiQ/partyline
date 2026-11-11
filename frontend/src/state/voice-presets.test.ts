import { afterEach, describe, expect, it, vi } from "vitest";
import { VoicePresets } from "./voice-presets.svelte.js";
import { voiceApi } from "../lib/voice-api";
import type { AsrSettings } from "../lib/asr-api";

const LISTING: AsrSettings = {
  default: "a",
  presets: ["a", "b"].map((name) => ({
    name,
    kind: "command",
    available: true,
    source: "database",
    editable: true,
    overrides_config: false,
    is_default: name === "a",
    can_be_default: true,
    fields: {},
  })),
};

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("voice presets store", () => {
  it("waits for pushed snapshots and never retry-fetches, even after an error", async () => {
    vi.useFakeTimers();
    const fetch = vi.spyOn(voiceApi, "presets");
    const store = new VoicePresets();
    store.error = "disconnected";
    store.ensure();
    await vi.advanceTimersByTimeAsync(600_000);
    expect(fetch).not.toHaveBeenCalled();
    expect(store.listing).toBeNull();
    store.receive(LISTING);
    expect(store.listing).toEqual(LISTING);
    expect(store.settings).toEqual(LISTING);
    expect(store.error).toBeNull();
    expect(store.loading).toBe(false);
    store.receive({ default: "new", presets: [] });
    expect(store.listing?.default).toBe("new");
    expect(store.revision).toBe(2);
  });

  it("remembers this browser's pick and falls back when it cannot run", () => {
    const store = new VoicePresets();
    store.receive(LISTING);
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
