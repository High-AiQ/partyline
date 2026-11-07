import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VoiceRecorder } from "./voice-recorder";
import { FALLBACK_NOTICE } from "./mic-device";
import { SILENCE_MS } from "./mic-meter";
import { FakeAudioContext, fakeAudioContext, fakeMicStream, gone } from "./mic-fakes";
import type { RecorderPhase, RecorderSources } from "./voice-recorder";

class FakeRecorder {
  state = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(this.data) });
    this.onstop?.();
  }
  data: string[] = ["audio"];
}

function setup(options: { reject?: string; throwOnCreate?: boolean; empty?: boolean; max?: number } = {}) {
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track] } as unknown as MediaStream;
  const fake = new FakeRecorder();
  if (options.empty) fake.data = [];
  const getUserMedia = vi.fn(() =>
    options.reject ? Promise.reject(new DOMException("x", options.reject)) : Promise.resolve(stream),
  );
  const sources: RecorderSources = {
    getUserMedia,
    createRecorder: vi.fn(() => {
      if (options.throwOnCreate) throw new Error("no");
      return fake as unknown as MediaRecorder;
    }),
    isTypeSupported: () => true,
  };
  const phases: RecorderPhase[] = [];
  const hooks = {
    onphase: (p: RecorderPhase) => phases.push(p),
    onelapsed: vi.fn(),
    ontake: vi.fn(),
    onerror: vi.fn(),
  };
  const recorder = new VoiceRecorder(sources, hooks, options.max);
  return { recorder, hooks, track, fake, phases, getUserMedia };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("VoiceRecorder", () => {
  it("records, stops on the second click, releases the mic and delivers the take", async () => {
    const { recorder, hooks, track, phases } = setup();
    await recorder.toggle();
    expect(recorder.phase).toBe("recording");
    vi.advanceTimersByTime(1000);
    expect(hooks.onelapsed).toHaveBeenLastCalledWith(1000);
    await recorder.toggle();
    expect(track.stop).toHaveBeenCalled();
    expect(phases).toEqual(["starting", "recording", "idle"]);
    expect(hooks.ontake).toHaveBeenCalledTimes(1);
    expect((hooks.ontake.mock.calls[0]?.[0] as Blob).size).toBeGreaterThan(0);
  });

  it("stops by itself at the cap", async () => {
    const { recorder, hooks, track } = setup({ max: 5000 });
    await recorder.start();
    vi.advanceTimersByTime(4999);
    expect(recorder.phase).toBe("recording");
    vi.advanceTimersByTime(2);
    expect(recorder.phase).toBe("idle");
    expect(track.stop).toHaveBeenCalled();
    expect(hooks.ontake).toHaveBeenCalled();
  });

  it("reports a denied permission and stays idle", async () => {
    const { recorder, hooks } = setup({ reject: "NotAllowedError" });
    await recorder.toggle();
    expect(recorder.phase).toBe("idle");
    expect(hooks.onerror).toHaveBeenCalledWith(expect.stringMatching(/denied/));
  });

  it("releases the mic when the recorder cannot be created", async () => {
    const { recorder, hooks, track } = setup({ throwOnCreate: true });
    await recorder.start();
    expect(track.stop).toHaveBeenCalled();
    expect(recorder.phase).toBe("idle");
    expect(hooks.onerror).toHaveBeenCalled();
  });

  it("refuses an empty take", async () => {
    const { recorder, hooks } = setup({ empty: true });
    await recorder.start();
    recorder.stop();
    expect(hooks.ontake).not.toHaveBeenCalled();
    expect(hooks.onerror).toHaveBeenCalledWith("nothing was recorded");
  });

  it("ignores a second start while starting and stop while idle", async () => {
    const { recorder, getUserMedia } = setup();
    const first = recorder.start();
    await recorder.toggle();
    await first;
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    recorder.stop();
    recorder.stop();
    const idle = setup().recorder;
    idle.stop();
    expect(idle.phase).toBe("idle");
  });

  it("cancel drops the take and frees the mic", async () => {
    const { recorder, hooks, track } = setup();
    await recorder.start();
    recorder.cancel();
    expect(track.stop).toHaveBeenCalled();
    expect(hooks.ontake).not.toHaveBeenCalled();
    expect(recorder.phase).toBe("idle");
  });

  it("surfaces a recorder error and releases the mic", async () => {
    const { recorder, hooks, track, fake } = setup();
    await recorder.start();
    fake.onerror?.();
    expect(track.stop).toHaveBeenCalled();
    expect(hooks.onerror).toHaveBeenCalledWith("recording failed");
    expect(recorder.phase).toBe("idle");
  });

  it("does not record when cancelled while the mic permission is pending", async () => {
    const track = { stop: vi.fn() };
    const stream = { getTracks: () => [track] } as unknown as MediaStream;
    let grant: (s: MediaStream) => void = () => undefined;
    const createRecorder = vi.fn();
    const hooks = { onphase: vi.fn(), onelapsed: vi.fn(), ontake: vi.fn(), onerror: vi.fn() };
    const recorder = new VoiceRecorder(
      {
        getUserMedia: () =>
          new Promise<MediaStream>((resolve) => {
            grant = resolve;
          }),
        createRecorder,
        isTypeSupported: () => true,
      },
      hooks,
    );
    const pending = recorder.start();
    recorder.cancel();
    grant(stream);
    await pending;
    expect(createRecorder).not.toHaveBeenCalled();
    expect(track.stop).toHaveBeenCalled();
    expect(recorder.phase).toBe("idle");
    expect(hooks.ontake).not.toHaveBeenCalled();
  });

  it("ignores late events from a cancelled take once a new take has started", async () => {
    const made: FakeRecorder[] = [];
    const track = { stop: vi.fn() };
    const stream = { getTracks: () => [track] } as unknown as MediaStream;
    const hooks = { onphase: vi.fn(), onelapsed: vi.fn(), ontake: vi.fn(), onerror: vi.fn() };
    const recorder = new VoiceRecorder(
      {
        getUserMedia: () => Promise.resolve(stream),
        createRecorder: () => {
          const fake = new FakeRecorder();
          // A real recorder flushes asynchronously: stop() only queues its events.
          fake.stop = () => {
            fake.state = "inactive";
          };
          made.push(fake);
          return fake as unknown as MediaRecorder;
        },
        isTypeSupported: () => true,
      },
      hooks,
    );
    await recorder.start();
    const first = made[0];
    const late = first?.ondataavailable;
    const lateStop = first?.onstop;
    const lateError = first?.onerror;
    recorder.cancel();
    await recorder.start();
    // Take A's queued events arrive after take B began (handlers read before cancel detached them).
    queueMicrotask(() => late?.({ data: new Blob(["PRIVATE A"]) }));
    queueMicrotask(() => lateError?.());
    queueMicrotask(() => lateStop?.());
    await Promise.resolve();
    await Promise.resolve();
    expect(recorder.phase).toBe("recording");
    expect(hooks.onerror).not.toHaveBeenCalled();
    const second = made[1];
    second?.ondataavailable?.({ data: new Blob(["PUBLIC B"]) });
    second?.onstop?.();
    expect(hooks.ontake).toHaveBeenCalledTimes(1);
    const blob = hooks.ontake.mock.calls[0]?.[0] as Blob;
    expect(blob.size).toBe("PUBLIC B".length);
  });

  it("a take that stops by itself leaves no timers behind for the next take", async () => {
    const { recorder, hooks, track, fake } = setup({ max: 1000 });
    await recorder.start();
    vi.advanceTimersByTime(300);
    // The source track ended (device unplugged): the recorder stops without stop().
    fake.state = "inactive";
    fake.ondataavailable?.({ data: new Blob(["a"]) });
    fake.onstop?.();
    expect(recorder.phase).toBe("idle");
    expect(hooks.ontake).toHaveBeenCalledTimes(1);
    expect(track.stop).toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    await recorder.start();
    expect(vi.getTimerCount()).toBe(2);
    // Past take A's old cap deadline (t=1000): take B (cap at t=1300) must keep recording.
    vi.advanceTimersByTime(800);
    expect(recorder.phase).toBe("recording");
    vi.advanceTimersByTime(500);
    expect(recorder.phase).toBe("idle");
    expect(vi.getTimerCount()).toBe(0);
  });
});

function metered(
  options: { deviceId?: string | null; rejectFirst?: "NotFoundError" | "OverconstrainedError" } = {},
) {
  const { stream, stop } = fakeMicStream("Headset (Jabra)");
  const getUserMedia = vi.fn<(c: MediaStreamConstraints) => Promise<MediaStream>>(() =>
    Promise.resolve(stream),
  );
  if (options.rejectFirst) getUserMedia.mockRejectedValueOnce(gone(options.rejectFirst));
  const sources: RecorderSources = {
    getUserMedia,
    createRecorder: () => new FakeRecorder() as unknown as MediaRecorder,
    isTypeSupported: () => true,
    micDeviceId: () => options.deviceId ?? null,
    createAudioContext: fakeAudioContext,
  };
  const hooks = {
    onphase: vi.fn(),
    onelapsed: vi.fn(),
    ontake: vi.fn(),
    onerror: vi.fn(),
    onlevel: vi.fn(),
    onsilent: vi.fn(),
    onmic: vi.fn(),
    onnotice: vi.fn(),
  };
  return { recorder: new VoiceRecorder(sources, hooks), hooks, getUserMedia, stop };
}

describe("VoiceRecorder mic choice", () => {
  beforeEach(() => {
    FakeAudioContext.made = [];
  });

  it("opens the chosen device by exact id", async () => {
    const { recorder, getUserMedia, hooks } = metered({ deviceId: "jabra-1" });
    await recorder.start();
    expect(getUserMedia).toHaveBeenCalledExactlyOnceWith({ audio: { deviceId: { exact: "jabra-1" } } });
    expect(hooks.onnotice).not.toHaveBeenCalled();
  });

  it("asks for any mic when none is chosen", async () => {
    const { recorder, getUserMedia } = metered();
    await recorder.start();
    expect(getUserMedia).toHaveBeenCalledExactlyOnceWith({ audio: true });
  });

  it.each(["NotFoundError", "OverconstrainedError"] as const)(
    "falls back to the default mic with a notice when the chosen one is gone (%s)",
    async (rejectFirst) => {
      const { recorder, getUserMedia, hooks } = metered({ deviceId: "gone", rejectFirst });
      await recorder.start();
      expect(getUserMedia).toHaveBeenNthCalledWith(1, { audio: { deviceId: { exact: "gone" } } });
      expect(getUserMedia).toHaveBeenNthCalledWith(2, { audio: true });
      expect(hooks.onnotice).toHaveBeenCalledExactlyOnceWith(FALLBACK_NOTICE);
      expect(recorder.phase).toBe("recording");
    },
  );

  it("names the mic in use", async () => {
    const { recorder, hooks } = metered();
    await recorder.start();
    expect(hooks.onmic).toHaveBeenCalledWith("Headset (Jabra)");
  });
});

describe("VoiceRecorder level meter", () => {
  beforeEach(() => {
    FakeAudioContext.made = [];
  });

  it("reports the live level while recording", async () => {
    const { recorder, hooks } = metered();
    await recorder.start();
    FakeAudioContext.last().analyser.amplitude = 0.05;
    vi.advanceTimersByTime(100);
    expect(hooks.onlevel).toHaveBeenLastCalledWith(expect.closeTo(0.3, 5));
  });

  it("raises the no-input hint after 3 s of silence and clears it when sound returns", async () => {
    const { recorder, hooks } = metered();
    await recorder.start();
    vi.advanceTimersByTime(SILENCE_MS - 100);
    expect(hooks.onsilent).not.toHaveBeenCalled();
    vi.advanceTimersByTime(100);
    expect(hooks.onsilent).toHaveBeenLastCalledWith(true);
    FakeAudioContext.last().analyser.amplitude = 0.2;
    vi.advanceTimersByTime(100);
    expect(hooks.onsilent).toHaveBeenLastCalledWith(false);
  });

  it("still records when Web Audio is missing", async () => {
    const { stream } = fakeMicStream();
    const sources: RecorderSources = {
      getUserMedia: () => Promise.resolve(stream),
      createRecorder: () => new FakeRecorder() as unknown as MediaRecorder,
      isTypeSupported: () => true,
    };
    const recorder = new VoiceRecorder(sources, {
      onphase: vi.fn(),
      onelapsed: vi.fn(),
      ontake: vi.fn(),
      onerror: vi.fn(),
    });
    await recorder.start();
    expect(recorder.phase).toBe("recording");
  });
});

describe("VoiceRecorder audio cleanup", () => {
  beforeEach(() => {
    FakeAudioContext.made = [];
  });

  it("closes the AudioContext and stops the tracks on stop", async () => {
    const { recorder, stop, hooks } = metered();
    await recorder.start();
    const context = FakeAudioContext.last();
    expect(context.closed).toBe(false);
    recorder.stop();
    expect(context.closed).toBe(true);
    expect(stop).toHaveBeenCalled();
    expect(hooks.onlevel).toHaveBeenLastCalledWith(0);
    expect(hooks.onsilent).toHaveBeenLastCalledWith(false);
  });

  it("closes the AudioContext and stops the tracks on cancel", async () => {
    const { recorder, stop } = metered();
    await recorder.start();
    const context = FakeAudioContext.last();
    recorder.cancel();
    expect(context.closed).toBe(true);
    expect(stop).toHaveBeenCalled();
    vi.advanceTimersByTime(SILENCE_MS * 2);
  });

  it("opens no AudioContext for a start cancelled while the mic was opening", async () => {
    const { recorder, stop } = metered();
    const starting = recorder.start();
    recorder.cancel();
    await starting;
    expect(stop).toHaveBeenCalled();
    expect(FakeAudioContext.made).toHaveLength(0);
  });

  it("a stale pending start released late leaves the newer take's meter running", async () => {
    const stale = fakeMicStream("Old");
    const fresh = fakeMicStream("New");
    let resolveStale: (stream: MediaStream) => void = () => undefined;
    const getUserMedia = vi
      .fn<(c: MediaStreamConstraints) => Promise<MediaStream>>()
      .mockReturnValueOnce(new Promise((resolve) => (resolveStale = resolve)))
      .mockResolvedValueOnce(fresh.stream);
    const sources: RecorderSources = {
      getUserMedia,
      createRecorder: () => new FakeRecorder() as unknown as MediaRecorder,
      isTypeSupported: () => true,
      createAudioContext: fakeAudioContext,
    };
    const hooks = {
      onphase: vi.fn(),
      onelapsed: vi.fn(),
      ontake: vi.fn(),
      onerror: vi.fn(),
      onsilent: vi.fn(),
    };
    const recorder = new VoiceRecorder(sources, hooks);
    const first = recorder.start();
    recorder.cancel();
    await recorder.start();
    const context = FakeAudioContext.last();
    resolveStale(stale.stream);
    await first;
    expect(stale.stop).toHaveBeenCalled();
    expect(recorder.phase).toBe("recording");
    expect(context.closed).toBe(false);
    vi.advanceTimersByTime(SILENCE_MS);
    expect(hooks.onsilent).toHaveBeenLastCalledWith(true);
    expect(fresh.stop).not.toHaveBeenCalled();
  });

  it("closes the AudioContext when the take ends by itself", async () => {
    const { recorder } = metered({});
    await recorder.start();
    const context = FakeAudioContext.last();
    vi.advanceTimersByTime(5 * 60 * 1000 + 1);
    expect(recorder.phase).toBe("idle");
    expect(context.closed).toBe(true);
  });
});
