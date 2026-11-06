import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VoiceRecorder } from "./voice-recorder";
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
