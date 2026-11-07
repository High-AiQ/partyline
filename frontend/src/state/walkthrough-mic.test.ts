import { describe, expect, it } from "vitest";
import { WalkthroughMic } from "./walkthrough-mic.svelte";

describe("walkthrough microphone", () => {
  it("reports a silent take only when the meter detected no input throughout", () => {
    const mic = new WalkthroughMic();
    expect(mic.noInput).toBe(false);
    mic.takeHooks.onsilent(true);
    expect(mic.noInput).toBe(true);
    mic.takeHooks.onlevel(0.02);
    expect(mic.noInput).toBe(false);
    mic.takeHooks.onsilent(true);
    expect(mic.noInput).toBe(false);
    mic.resetTake();
    mic.takeHooks.onsilent(true);
    expect(mic.noInput).toBe(true);
  });
});
