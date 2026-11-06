/**
 * One microphone take: getUserMedia + MediaRecorder behind a small state
 * machine. The mic track is released the moment recording stops, and the audio
 * lives only in memory until the caller has transcribed it.
 */
import { MAX_TAKE_MS, describeMicError, pickMimeType } from "./voice";

export type RecorderPhase = "idle" | "starting" | "recording";

export interface RecorderHooks {
  onphase(phase: RecorderPhase): void;
  onelapsed(ms: number): void;
  ontake(blob: Blob): void;
  onerror(reason: string): void;
}

export interface RecorderSources {
  getUserMedia(constraints: MediaStreamConstraints): Promise<MediaStream>;
  createRecorder(stream: MediaStream, mimeType: string | undefined): MediaRecorder;
  isTypeSupported(type: string): boolean;
}

export function browserSources(): RecorderSources {
  return {
    getUserMedia: (constraints) => navigator.mediaDevices.getUserMedia(constraints),
    createRecorder: (stream, mimeType) => new MediaRecorder(stream, mimeType ? { mimeType } : undefined),
    isTypeSupported: (type) => MediaRecorder.isTypeSupported(type),
  };
}

export class VoiceRecorder {
  phase: RecorderPhase = "idle";
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private startedAt = 0;
  private ticker: ReturnType<typeof setInterval> | null = null;
  private cap: ReturnType<typeof setTimeout> | null = null;
  /** Bumped by cancel(); a start that finds it changed was cancelled while the mic opened. */
  private generation = 0;

  constructor(
    private readonly sources: RecorderSources,
    private readonly hooks: RecorderHooks,
    private readonly maxMs = MAX_TAKE_MS,
  ) {}

  private setPhase(phase: RecorderPhase): void {
    this.phase = phase;
    this.hooks.onphase(phase);
  }

  /** A click: start when idle, stop when recording, ignore while the mic opens. */
  toggle(): Promise<void> {
    if (this.phase === "recording") {
      this.stop();
      return Promise.resolve();
    }
    return this.phase === "idle" ? this.start() : Promise.resolve();
  }

  async start(): Promise<void> {
    if (this.phase !== "idle") return;
    this.setPhase("starting");
    const started = this.generation;
    let stream: MediaStream;
    try {
      stream = await this.sources.getUserMedia({ audio: true });
    } catch (error) {
      if (started !== this.generation) return;
      this.setPhase("idle");
      this.hooks.onerror(describeMicError(error));
      return;
    }
    if (started !== this.generation) {
      // Cancelled while the browser was asking for the mic: do not record, free the track.
      this.releaseTracks(stream);
      return;
    }
    try {
      const recorder = this.sources.createRecorder(
        stream,
        pickMimeType((type) => this.sources.isTypeSupported(type)),
      );
      this.stream = stream;
      this.recorder = recorder;
      // Each take owns its chunks and its handlers: MediaRecorder delivers the final
      // dataavailable asynchronously, and a late event from a dropped take must never
      // reach the next one.
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      };
      recorder.onstop = () => {
        if (this.recorder === recorder) this.finish(chunks, recorder.mimeType);
      };
      recorder.onerror = () => {
        if (this.recorder === recorder) this.abort("recording failed");
      };
      recorder.start();
    } catch {
      this.releaseTracks(stream);
      this.stream = null;
      this.recorder = null;
      this.setPhase("idle");
      this.hooks.onerror("could not start recording");
      return;
    }
    this.startedAt = Date.now();
    this.hooks.onelapsed(0);
    this.ticker = setInterval(() => {
      this.hooks.onelapsed(Date.now() - this.startedAt);
    }, 250);
    const take = this.recorder;
    this.cap = setTimeout(() => {
      // Per-take: only the take that armed this timer may be stopped by it.
      if (this.recorder === take) this.stop();
    }, this.maxMs);
    this.setPhase("recording");
  }

  stop(): void {
    if (this.phase !== "recording" || !this.recorder) return;
    this.clearTimers();
    const stream = this.stream;
    try {
      if (this.recorder.state !== "inactive") this.recorder.stop();
    } finally {
      // Release the mic now so the OS indicator goes out, not when the data lands.
      this.releaseTracks(stream);
    }
  }

  /** Drop the take without transcribing it (unmount, line switch). */
  cancel(): void {
    this.generation++;
    this.detach(this.recorder);
    this.stop();
    this.releaseTracks(this.stream);
    this.clearTimers();
    this.reset();
  }

  private detach(recorder: MediaRecorder | null): void {
    if (!recorder) return;
    recorder.ondataavailable = null;
    recorder.onstop = null;
    recorder.onerror = null;
  }

  private finish(chunks: Blob[], mimeType: string): void {
    const blob = new Blob(chunks, { type: mimeType || "audio/webm" });
    // The recorder may have stopped by itself (source track ended): its timers and
    // tracks are still live and must not outlive this take.
    this.clearTimers();
    this.releaseTracks(this.stream);
    this.reset();
    if (blob.size === 0) {
      this.hooks.onerror("nothing was recorded");
      return;
    }
    this.hooks.ontake(blob);
  }

  private abort(reason: string): void {
    this.detach(this.recorder);
    this.clearTimers();
    this.releaseTracks(this.stream);
    this.reset();
    this.hooks.onerror(reason);
  }

  private reset(): void {
    this.recorder = null;
    this.stream = null;
    if (this.phase !== "idle") this.setPhase("idle");
  }

  private clearTimers(): void {
    if (this.ticker) clearInterval(this.ticker);
    if (this.cap) clearTimeout(this.cap);
    this.ticker = null;
    this.cap = null;
  }

  private releaseTracks(stream: MediaStream | null): void {
    stream?.getTracks().forEach((track) => {
      track.stop();
    });
  }
}
