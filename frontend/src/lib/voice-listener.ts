/** Continuous local Silero detection; only complete speech takes leave this class. */
import type { RealTimeVADOptions } from "@ricky0123/vad-web";
import { FALLBACK_NOTICE, openMicStream, readSavedMic } from "./mic-device";
import { browserAudioContext } from "./mic-meter";
import { describeMicError } from "./voice";

export type ListeningPhase = "off" | "starting" | "listening" | "speaking";
export interface VadHandle {
  start: () => Promise<void>;
  pause: () => Promise<void>;
  destroy: () => Promise<void>;
}
export interface ListenerSources {
  getUserMedia: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  micDeviceId: () => string | null;
  createContext: () => AudioContext;
  createVad: (options: Partial<RealTimeVADOptions>, onerror: (error: unknown) => void) => Promise<VadHandle>;
}
export interface ListenerHooks {
  onphase: (phase: ListeningPhase) => void;
  ontake: (blob: Blob) => void;
  onerror: (message: string) => void;
  onnotice: (message: string) => void;
}
export const HANDS_FREE_CAP_MS = 60_000;
export const PRE_ROLL_MS = 300;

export function browserListenerSources(): ListenerSources {
  return {
    getUserMedia: (constraints) => navigator.mediaDevices.getUserMedia(constraints),
    micDeviceId: readSavedMic,
    createContext: browserAudioContext,
    createVad: async (options, onerror) => {
      const { createSileroVad } = await import("./silero-vad");
      return createSileroVad(options, onerror);
    },
  };
}

/** PCM16 mono WAV: supported by every existing recognizer, with no codec delay. */
export function speechWav(samples: Float32Array, maxMs = HANDS_FREE_CAP_MS): Blob {
  const count = Math.min(samples.length, 16 * maxMs);
  const bytes = new ArrayBuffer(44 + count * 2);
  const view = new DataView(bytes);
  const write = (offset: number, value: string): void => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  write(0, "RIFF");
  view.setUint32(4, 36 + count * 2, true);
  write(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true);
  view.setUint32(28, 32000, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, count * 2, true);
  for (let i = 0; i < count; i++) {
    const value = Math.max(-1, Math.min(1, samples[i] ?? 0));
    view.setInt16(44 + i * 2, value * (value < 0 ? 32768 : 32767), true);
  }
  return new Blob([bytes], { type: "audio/wav" });
}

export class VoiceListener {
  private generation = 0;
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private vad: VadHandle | null = null;
  private cap: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private sources: ListenerSources,
    private hooks: ListenerHooks,
  ) {}

  async start(pauseMs: number): Promise<void> {
    this.stop();
    const generation = this.generation;
    this.hooks.onphase("starting");
    try {
      // Resume inside the toggle gesture, before model loading awaits anything.
      this.context = this.sources.createContext();
      await this.context.resume();
      if (generation !== this.generation) return;
      const { stream, fellBack } = await openMicStream(
        (constraints) => this.sources.getUserMedia(constraints),
        this.sources.micDeviceId(),
      );
      if (generation !== this.generation) {
        stream.getTracks().forEach((track) => {
          track.stop();
        });
        return;
      }
      this.stream = stream;
      if (fellBack) this.hooks.onnotice(FALLBACK_NOTICE);
      const current = (): boolean => generation === this.generation;
      const vad = await this.sources.createVad(
        {
          model: "v5",
          audioContext: this.context,
          startOnLoad: false,
          getStream: () => Promise.resolve(stream),
          positiveSpeechThreshold: 0.7,
          negativeSpeechThreshold: 0.35,
          preSpeechPadMs: PRE_ROLL_MS,
          redemptionMs: pauseMs,
          // v5 frames are 32 ms; round up so at least 400 ms must score as speech.
          minSpeechMs: 416,
          submitUserSpeechOnPause: true,
          onSpeechStart: () => {
            if (!current()) return;
            this.hooks.onphase("speaking");
            this.clearCap();
            this.cap = setTimeout(() => {
              void this.capTake(generation);
            }, HANDS_FREE_CAP_MS - PRE_ROLL_MS);
          },
          onVADMisfire: () => {
            if (!current()) return;
            this.clearCap();
            this.hooks.onphase("listening");
          },
          onSpeechEnd: (audio) => {
            if (!current()) return;
            this.clearCap();
            this.hooks.onphase("listening");
            this.hooks.ontake(speechWav(audio));
          },
        },
        (error) => {
          if (!current()) return;
          this.stop();
          this.hooks.onerror(error instanceof Error ? error.message : "speech detection failed");
        },
      );
      if (!current()) {
        await vad.destroy().catch(() => undefined);
        return;
      }
      this.vad = vad;
      await vad.start();
      if (current()) this.hooks.onphase("listening");
    } catch (error) {
      if (generation !== this.generation) return;
      this.stop();
      // Some VAD startup failures happen before its destroy() can run; tracks and
      // the external AudioContext are always ours to release regardless.
      this.hooks.onerror(describeMicError(error));
    }
  }

  stop(): void {
    this.generation++;
    this.clearCap();
    this.stream?.getTracks().forEach((track) => {
      track.stop();
    });
    this.stream = null;
    const vad = this.vad;
    this.vad = null;
    void vad?.destroy().catch(() => undefined);
    void this.context?.close().catch(() => undefined);
    this.context = null;
    this.hooks.onphase("off");
  }

  private async capTake(generation: number): Promise<void> {
    const vad = this.vad;
    if (!vad || generation !== this.generation) return;
    try {
      await vad.pause(); // submits a qualifying take and resets the model buffer
      if (generation === this.generation) await vad.start();
    } catch {
      if (generation !== this.generation) return;
      this.stop();
      this.hooks.onerror("could not continue hands-free listening");
    }
  }

  private clearCap(): void {
    if (this.cap !== null) clearTimeout(this.cap);
    this.cap = null;
  }
}
