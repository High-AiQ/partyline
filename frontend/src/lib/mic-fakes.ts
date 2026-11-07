/** Fake Web Audio and a fake mic stream for tests: no real audio, no real time. */
import { vi } from "vitest";

export class FakeAnalyser {
  fftSize = 2048;
  /** The constant sample value the next read returns; its RMS is |amplitude|. */
  amplitude = 0;
  getFloatTimeDomainData(into: Float32Array): void {
    into.fill(this.amplitude);
  }
}

export class FakeAudioContext {
  static made: FakeAudioContext[] = [];
  readonly analyser = new FakeAnalyser();
  closed = false;
  readonly source = { connect: vi.fn(), disconnect: vi.fn() };
  constructor() {
    FakeAudioContext.made.push(this);
  }
  /** The context most recently created. */
  static last(): FakeAudioContext {
    const found = FakeAudioContext.made.at(-1);
    if (!found) throw new Error("no AudioContext was created");
    return found;
  }
  resume(): Promise<void> {
    return Promise.resolve();
  }
  createAnalyser(): AnalyserNode {
    return this.analyser as unknown as AnalyserNode;
  }
  createMediaStreamSource(): MediaStreamAudioSourceNode {
    return this.source as unknown as MediaStreamAudioSourceNode;
  }
  close(): Promise<void> {
    this.closed = true;
    return Promise.resolve();
  }
}

export function fakeAudioContext(): AudioContext {
  return new FakeAudioContext() as unknown as AudioContext;
}

export function fakeMicStream(label = "Headset (Jabra)"): {
  stream: MediaStream;
  stop: ReturnType<typeof vi.fn>;
} {
  const stop = vi.fn();
  const stream = { getTracks: () => [{ stop, label }] } as unknown as MediaStream;
  return { stream, stop };
}

export function gone(name: "OverconstrainedError" | "NotFoundError" | "NotAllowedError"): DOMException {
  return new DOMException("device", name);
}
