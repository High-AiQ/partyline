import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SAMPLE_MS, SILENCE_MS, displayLevel, startMeter } from "./mic-meter";
import { FakeAudioContext, fakeAudioContext, fakeMicStream } from "./mic-fakes";

beforeEach(() => {
  vi.useFakeTimers();
  FakeAudioContext.made = [];
});
afterEach(() => vi.useRealTimers());

function start() {
  const hooks = { onlevel: vi.fn(), onsilent: vi.fn() };
  const meter = startMeter(fakeMicStream().stream, fakeAudioContext, hooks);
  return { hooks, meter, context: FakeAudioContext.last() };
}

describe("startMeter", () => {
  it("reports the level of the stream on every sample", () => {
    const { hooks, context } = start();
    context.analyser.amplitude = 0.05;
    vi.advanceTimersByTime(SAMPLE_MS);
    expect(hooks.onlevel).toHaveBeenLastCalledWith(expect.closeTo(displayLevel(0.05), 5));
    context.analyser.amplitude = 0.5;
    vi.advanceTimersByTime(SAMPLE_MS);
    expect(hooks.onlevel).toHaveBeenLastCalledWith(1);
  });

  it("raises the silence hint after 3 s near zero, and not a moment earlier", () => {
    const { hooks } = start();
    vi.advanceTimersByTime(SILENCE_MS - SAMPLE_MS);
    expect(hooks.onsilent).not.toHaveBeenCalled();
    vi.advanceTimersByTime(SAMPLE_MS);
    expect(hooks.onsilent).toHaveBeenCalledExactlyOnceWith(true);
    vi.advanceTimersByTime(10_000);
    expect(hooks.onsilent).toHaveBeenCalledTimes(1);
  });

  it("clears the hint when sound returns, and sound resets the 3 s clock", () => {
    const { hooks, context } = start();
    vi.advanceTimersByTime(SILENCE_MS - SAMPLE_MS);
    context.analyser.amplitude = 0.1;
    vi.advanceTimersByTime(SAMPLE_MS);
    context.analyser.amplitude = 0;
    vi.advanceTimersByTime(SILENCE_MS - SAMPLE_MS);
    expect(hooks.onsilent).not.toHaveBeenCalled();
    vi.advanceTimersByTime(SAMPLE_MS);
    expect(hooks.onsilent).toHaveBeenLastCalledWith(true);
    context.analyser.amplitude = 0.1;
    vi.advanceTimersByTime(SAMPLE_MS);
    expect(hooks.onsilent).toHaveBeenLastCalledWith(false);
  });

  it("closes the context, disconnects the source and stops sampling", () => {
    const { hooks, meter, context } = start();
    meter?.close();
    expect(context.closed).toBe(true);
    expect(context.source.disconnect).toHaveBeenCalled();
    vi.advanceTimersByTime(SILENCE_MS * 2);
    expect(hooks.onlevel).not.toHaveBeenCalled();
    expect(hooks.onsilent).not.toHaveBeenCalled();
    expect(() => meter?.close()).not.toThrow();
  });

  it("is absent without Web Audio, and swallows a broken one", () => {
    expect(startMeter(fakeMicStream().stream, undefined, {})).toBeNull();
    const broken = (): AudioContext => {
      throw new Error("blocked");
    };
    expect(startMeter(fakeMicStream().stream, broken, {})).toBeNull();
  });
});
