/**
 * One microphone take: getUserMedia + MediaRecorder behind a small state
 * machine. The mic track is released the moment recording stops, and the audio
 * lives only in memory until the caller has transcribed it.
 */
import { FALLBACK_NOTICE, openMicStream, readSavedMic, streamMicLabel } from "./mic-device";
import { browserAudioContext, startMeter } from "./mic-meter";
import type { MicMeter } from "./mic-meter";
import { MAX_TAKE_MS, describeMicError, pickMimeType } from "./voice";

export type RecorderPhase = "idle" | "starting" | "recording";

/** What a screen may show about the live mic; every hook is optional. */
export interface MicHooks {
  /** Input level 0..1 while a take is open. */
  onlevel?(level: number): void;
  /** True once the level has stayed near zero for about 3 s; false again when sound returns. */
  onsilent?(silent: boolean): void;
  /** The browser's name for the mic in use, when it gives one. */
  onmic?(label: string | null): void;
  /** The chosen mic was gone and the default one is used instead. */
  onnotice?(message: string): void;
}

export interface RecorderHooks extends MicHooks {
  onphase(phase: RecorderPhase): void;
  onelapsed(ms: number): void;
  ontake(blob: Blob): void;
  onerror(reason: string): void;
}

export interface RecorderSources {
  getUserMedia(constraints: MediaStreamConstraints): Promise<MediaStream>;
  createRecorder(stream: MediaStream, mimeType: string | undefined): MediaRecorder;
  isTypeSupported(type: string): boolean;
  /** The remembered mic choice; absent means the default device. */
  micDeviceId?: () => string | null;
  /** Web Audio for the level meter; absent means no meter. */
  createAudioContext?: () => AudioContext;
}

export function browserSources(): RecorderSources {
  return {
    getUserMedia: (constraints) => navigator.mediaDevices.getUserMedia(constraints),
    createRecorder: (stream, mimeType) => new MediaRecorder(stream, mimeType ? { mimeType } : undefined),
    isTypeSupported: (type) => MediaRecorder.isTypeSupported(type),
    micDeviceId: readSavedMic,
    createAudioContext: browserAudioContext,
  };
}

export class VoiceRecorder {
  phase: RecorderPhase = "idle";
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private startedAt = 0;
  private ticker: ReturnType<typeof setInterval> | null = null;
  private cap: ReturnType<typeof setTimeout> | null = null;
  private meter: MicMeter | null = null;
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
    let fellBack: boolean;
    try {
      ({ stream, fellBack } = await openMicStream(
        (constraints) => this.sources.getUserMedia(constraints),
        this.sources.micDeviceId?.() ?? null,
      ));
    } catch (error) {
      if (started !== this.generation) return;
      this.setPhase("idle");
      this.hooks.onerror(describeMicError(error));
      return;
    }
    if (started !== this.generation) {
      // Cancelled while the browser was asking for the mic: do not record, free the track.
      // Only the tracks: this.meter may already belong to a newer take.
      this.stopTracks(stream);
      return;
    }
    if (fellBack) this.hooks.onnotice?.(FALLBACK_NOTICE);
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
      this.hooks.onmic?.(streamMicLabel(stream));
      this.meter = startMeter(stream, this.sources.createAudioContext, this.hooks);
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
    // no-poll (d): local display ticker; no request
    this.ticker = setInterval(() => {
      this.hooks.onelapsed(Date.now() - this.startedAt);
    }, 250);
    const take = this.recorder;
    // no-poll (b): one-shot UI deadline; no state request
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
    if (this.meter) {
      this.meter.close();
      this.meter = null;
      this.hooks.onlevel?.(0);
      this.hooks.onsilent?.(false);
    }
    this.stopTracks(stream);
  }

  private stopTracks(stream: MediaStream | null): void {
    stream?.getTracks().forEach((track) => {
      track.stop();
    });
  }
}
