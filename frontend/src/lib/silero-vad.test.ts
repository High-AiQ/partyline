import { afterEach, describe, expect, it, vi } from "vitest";
import { createSileroVad } from "./silero-vad";
import type { SileroSources } from "./silero-vad";
import { fakeAudioContext, fakeMicStream, FakeAudioContext } from "./mic-fakes";
import { Message } from "@ricky0123/vad-web/dist/messages";
import type { Model } from "@ricky0123/vad-web/dist/models";

afterEach(() => {
  vi.restoreAllMocks();
});
function setup() {
  const model: Model = {
    process: vi.fn().mockResolvedValue({ isSpeech: 0.99, notSpeech: 0.01 }),
    reset_state: vi.fn(),
    release: vi.fn().mockResolvedValue(undefined),
  };
  const node = {
    port: { onmessage: null as ((event: MessageEvent<unknown>) => void) | null, postMessage: vi.fn() },
    onprocessorerror: null as (() => void) | null,
    disconnect: vi.fn(),
  };
  const sources: SileroSources = {
    load: () => Promise.resolve(model),
    worklet: () => Promise.resolve(node as unknown as AudioWorkletNode),
  };
  const context = fakeAudioContext();
  const options = { audioContext: context, getStream: () => Promise.resolve(fakeMicStream().stream) };
  const error = vi.fn();
  const frame = () => {
    node.port.onmessage?.(
      new MessageEvent("message", {
        data: { message: Message.AudioFrame, data: new Float32Array(512).buffer },
      }),
    );
  };
  return { sources, context, options, model, node, error, frame };
}
async function settle() {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

describe("Silero resource and inference ownership", () => {
  it("releases the model and node even when discarded before start", async () => {
    const s = setup();
    const vad = await createSileroVad(s.options, s.error, s.sources);
    await vad.destroy();
    await vad.destroy();
    expect(s.model.release).toHaveBeenCalledOnce();
    expect(s.node.disconnect).toHaveBeenCalledOnce();
    expect(FakeAudioContext.last().source.disconnect).toHaveBeenCalledOnce();
    expect(s.node.port.onmessage).toBeNull();
    expect(s.context.state).not.toBe("closed"); // caller owns the context
    await expect(vad.start()).rejects.toThrow("released");
  });

  it("releases a loaded model if worklet or source initialization fails", async () => {
    const s = setup();
    s.sources.worklet = () => Promise.reject(new Error("no worklet"));
    await expect(createSileroVad(s.options, s.error, s.sources)).rejects.toThrow("no worklet");
    expect(s.model.release).toHaveBeenCalledOnce();
    const t = setup();
    t.options.getStream = () => Promise.reject(new Error("mic gone"));
    await expect(createSileroVad(t.options, t.error, t.sources)).rejects.toThrow("mic gone");
    expect(t.model.release).toHaveBeenCalledOnce();
    expect(t.node.disconnect).toHaveBeenCalledOnce();
  });

  it("serializes recurrent inference and drains it before model release", async () => {
    const s = setup();
    const resolvers: (() => void)[] = [];
    vi.mocked(s.model.process).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvers.push(() => {
            resolve({ isSpeech: 0.99, notSpeech: 0.01 });
          });
        }),
    );
    const vad = await createSileroVad(s.options, s.error, s.sources);
    await vad.start();
    s.frame();
    s.frame();
    s.frame();
    expect(s.model.process).toHaveBeenCalledTimes(1);
    resolvers[0]?.();
    await settle();
    expect(s.model.process).toHaveBeenCalledTimes(2);
    const stop = vad.destroy();
    expect(s.model.release).not.toHaveBeenCalled();
    resolvers[1]?.();
    await stop;
    expect(s.model.process).toHaveBeenCalledTimes(2);
    expect(s.model.release).toHaveBeenCalledOnce();
  });

  it("reports inference/worklet errors and rejects malformed worklet frames", async () => {
    const s = setup();
    const vad = await createSileroVad(s.options, s.error, s.sources);
    await vad.start();
    s.node.port.onmessage?.(
      new MessageEvent("message", { data: { message: "AUDIO_FRAME", data: "not PCM" } }),
    );
    expect(s.model.process).not.toHaveBeenCalled();
    vi.mocked(s.model.process).mockRejectedValue(new Error("inference failed"));
    s.frame();
    await settle();
    expect(s.error).toHaveBeenCalledWith(expect.objectContaining({ message: "inference failed" }));
    s.node.onprocessorerror?.();
    expect(s.error).toHaveBeenLastCalledWith(
      expect.objectContaining({ message: "speech detection audio worklet failed" }),
    );
    await vad.destroy();
  });
});
