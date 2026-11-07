import { afterEach, describe, expect, it, vi } from "vitest";
import { SAVED_FLASH_MS, SaveTracker } from "./save-state";
import type { SaveSnapshot } from "./save-state";

afterEach(() => {
  vi.useRealTimers();
});

describe("SaveTracker", () => {
  it("reports saving, then saved, then fades back to idle on the clock", async () => {
    vi.useFakeTimers();
    const seen: SaveSnapshot[] = [];
    const tracker = new SaveTracker((state) => seen.push(state));
    await expect(tracker.run(() => Promise.resolve(7))).resolves.toBe(7);
    expect(seen.map((state) => state.phase)).toEqual(["saving", "saved"]);
    vi.advanceTimersByTime(SAVED_FLASH_MS - 1);
    expect(seen.at(-1)?.phase).toBe("saved");
    vi.advanceTimersByTime(1);
    expect(seen.at(-1)?.phase).toBe("idle");
  });

  it("reports the error and returns nothing; dispose cancels a pending fade", async () => {
    vi.useFakeTimers();
    const seen: SaveSnapshot[] = [];
    const tracker = new SaveTracker((state) => seen.push(state));
    await expect(tracker.run(() => Promise.reject(new Error("disk full")))).resolves.toBeUndefined();
    expect(seen.at(-1)).toEqual({ phase: "error", message: "disk full" });
    await expect(
      tracker.run(() => {
        // A non-Error rejection (a thrown string) falls back to the given message.
        // eslint-disable-next-line @typescript-eslint/only-throw-error
        throw "odd";
      }, "fallback"),
    ).resolves.toBeUndefined();
    expect(seen.at(-1)).toEqual({ phase: "error", message: "fallback" });
    await tracker.run(() => Promise.resolve());
    tracker.dispose();
    vi.advanceTimersByTime(SAVED_FLASH_MS);
    expect(seen.at(-1)?.phase).toBe("saved");
  });
});
