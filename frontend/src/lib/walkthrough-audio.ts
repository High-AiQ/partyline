/** Decode browser containers locally; the server only needs standard PCM WAV. */
import { speechWav } from "./voice-listener";

export type RecordingDecoder = (data: ArrayBuffer) => Promise<AudioBuffer>;

export async function walkthroughWav(
  recording: Blob,
  signal?: AbortSignal,
  decode: RecordingDecoder = (data) => new OfflineAudioContext(1, 1, 16000).decodeAudioData(data),
): Promise<Blob> {
  signal?.throwIfAborted();
  // decodeAudioData resamples to the context's 16 kHz rate. No playback or
  // microphone is opened, and the recording stays in memory.
  const audio = await decode(await recording.arrayBuffer());
  signal?.throwIfAborted();
  if (audio.sampleRate !== 16000 || !audio.length || !audio.numberOfChannels)
    throw new Error("Could not decode walkthrough audio");
  // MediaRecorder can stop a little after its timer; keep the allowed ten
  // minutes instead of rejecting the whole take for codec padding or jitter.
  const mono = new Float32Array(Math.min(audio.length, 16000 * 600));
  for (let channel = 0; channel < audio.numberOfChannels; channel++) {
    const samples = audio.getChannelData(channel);
    for (let i = 0; i < mono.length; i++)
      mono[i] = (mono[i] ?? 0) + (samples[i] ?? 0) / audio.numberOfChannels;
  }
  return speechWav(mono, 600_000);
}
