/**
 * A live input level read from a Web Audio AnalyserNode on the same stream the
 * recorder uses. Sampled on a timer, so a test drives it with fake timers.
 */

export const SAMPLE_MS = 100;
/** Quiet this long and the mic is probably muted or the wrong one. */
export const SILENCE_MS = 3000;
/** Root-mean-square below this is digital silence or a dead input. */
export const SILENT_RMS = 0.003;

export interface MeterHooks {
  /** 0..1, for drawing. */
  onlevel?(level: number): void;
  onsilent?(silent: boolean): void;
}

export interface MicMeter {
  close(): void;
}

export function displayLevel(rms: number): number {
  return Math.min(1, rms * 6);
}

/** Start metering; null when Web Audio is missing or fails, which must never stop recording. */
export function startMeter(
  stream: MediaStream,
  createContext: (() => AudioContext) | undefined,
  hooks: MeterHooks,
): MicMeter | null {
  if (!createContext) return null;
  let context: AudioContext | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  const close = (): void => {
    if (timer !== null) clearInterval(timer);
    timer = null;
    try {
      source?.disconnect();
    } catch {
      // already disconnected
    }
    source = null;
    // Closing the context frees the audio thread; a second close rejects, which is fine.
    void context?.close().catch(() => undefined);
    context = null;
  };
  try {
    context = createContext();
    void context.resume().catch(() => undefined);
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    source = context.createMediaStreamSource(stream);
    source.connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    let quietMs = 0;
    let silent = false;
    // no-poll (d): local display ticker; no request
    timer = setInterval(() => {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const value of samples) sum += value * value;
      const rms = Math.sqrt(sum / samples.length);
      hooks.onlevel?.(displayLevel(rms));
      quietMs = rms < SILENT_RMS ? quietMs + SAMPLE_MS : 0;
      const nowSilent = quietMs >= SILENCE_MS;
      if (nowSilent !== silent) {
        silent = nowSilent;
        hooks.onsilent?.(silent);
      }
    }, SAMPLE_MS);
  } catch {
    close();
    return null;
  }
  return { close };
}

export function browserAudioContext(): AudioContext {
  const win = window as unknown as {
    AudioContext?: typeof AudioContext;
    webkitAudioContext?: typeof AudioContext;
  };
  const Ctor = win.AudioContext ?? win.webkitAudioContext;
  if (!Ctor) throw new Error("no Web Audio");
  return new Ctor();
}
