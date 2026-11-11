import { describe, expect, it, vi } from "vitest";
import { walkthroughWav } from "./walkthrough-audio";

function buffer(channels: Float32Array[], sampleRate = 16000): AudioBuffer {
  return {
    sampleRate,
    length: channels[0]?.length ?? 0,
    duration: (channels[0]?.length ?? 0) / sampleRate,
    numberOfChannels: channels.length,
    getChannelData: (channel: number) => channels[channel] ?? new Float32Array(),
  } as AudioBuffer;
}

// jsdom's Blob has no arrayBuffer; the browser does.
function recording(): Blob {
  return { arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) } as Blob;
}

describe("walkthrough PCM encoding", () => {
  it("mixes decoded stereo into mono PCM16 WAV with its recording offsets intact", async () => {
    const decode = vi
      .fn()
      .mockResolvedValue(buffer([new Float32Array([0, 1, -1]), new Float32Array([0, 0, 0])]));
    const blob = await walkthroughWav(recording(), undefined, decode);
    const bytes = await new Promise<ArrayBuffer>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => {
        resolve(reader.result as ArrayBuffer);
      };
      reader.readAsArrayBuffer(blob);
    });
    const view = new DataView(bytes);
    expect(blob.type).toBe("audio/wav");
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getInt16(44, true)).toBe(0);
    expect(view.getInt16(46, true)).toBe(16383);
    expect(view.getInt16(48, true)).toBe(-16384);
  });

  it("keeps audio beyond the hands-free composer's sixty second cap", async () => {
    const samples = new Float32Array(16000 * 61);
    const blob = await walkthroughWav(recording(), undefined, () => Promise.resolve(buffer([samples])));
    expect(blob.size).toBe(44 + samples.length * 2);
  });

  it("caps recorder timer overshoot at ten minutes", async () => {
    const samples = new Float32Array(16000 * 601);
    const blob = await walkthroughWav(recording(), undefined, () => Promise.resolve(buffer([samples])));
    expect(blob.size).toBe(44 + 16000 * 600 * 2);
  });

  it("rejects empty and incorrectly decoded recordings", async () => {
    for (const decoded of [buffer([]), buffer([new Float32Array(2)], 48000)]) {
      await expect(walkthroughWav(recording(), undefined, () => Promise.resolve(decoded))).rejects.toThrow();
    }
  });

  it("does not submit a recording cancelled during decoding", async () => {
    const abort = new AbortController();
    const decode = (): Promise<AudioBuffer> => {
      abort.abort();
      return Promise.resolve(buffer([new Float32Array(2)]));
    };
    await expect(walkthroughWav(recording(), abort.signal, decode)).rejects.toThrow();
    const unused = vi.fn();
    await expect(walkthroughWav(recording(), abort.signal, unused)).rejects.toThrow();
    expect(unused).not.toHaveBeenCalled();
  });
});
