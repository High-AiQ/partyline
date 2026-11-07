/** Silero's model/segmenter/worklet with explicit ownership of inference and nodes. */
import * as ort from "onnxruntime-web/wasm";
import { z } from "zod";
import { dependencies } from "../../package.json";
const ASSET_PATH = `/assets/voice-${dependencies["@ricky0123/vad-web"]}-${dependencies["onnxruntime-web"]}/`;
import { FrameProcessor } from "@ricky0123/vad-web/dist/frame-processor";
import { Message } from "@ricky0123/vad-web/dist/messages";
import { Silero } from "@ricky0123/vad-web/dist/models";
import { getDefaultRealTimeVADOptions } from "@ricky0123/vad-web";
import type { RealTimeVADOptions } from "@ricky0123/vad-web";
import type { FrameProcessorEvent } from "@ricky0123/vad-web/dist/frame-processor";
import type { Model } from "@ricky0123/vad-web/dist/models";
import type { VadHandle } from "./voice-listener";

const AudioFrame = z.object({ message: z.literal(Message.AudioFrame), data: z.instanceof(ArrayBuffer) });
export interface SileroSources {
  load(): Promise<Model>;
  worklet(context: AudioContext): Promise<AudioWorkletNode>;
}
const browserSources: SileroSources = {
  load: () => {
    ort.env.wasm.wasmPaths = ASSET_PATH;
    ort.env.wasm.numThreads = 1;
    return Silero.new(ort, async () => {
      const response = await fetch(ASSET_PATH + "silero_vad_v5.onnx");
      if (!response.ok) throw new Error("could not load the speech detection model");
      return response.arrayBuffer();
    });
  },
  worklet: async (context) => {
    await context.audioWorklet.addModule(ASSET_PATH + "vad.worklet.bundle.min.js");
    return new AudioWorkletNode(context, "vad-helper-worklet", { processorOptions: { frameSamples: 512 } });
  },
};

/** The caller owns the microphone and AudioContext; this handle owns everything else.
 * Unlike MicVAD.destroy(), cleanup must also work before start() or after failed startup.
 */
export async function createSileroVad(
  options: Partial<RealTimeVADOptions>,
  onerror: (error: unknown) => void,
  sources: SileroSources = browserSources,
): Promise<VadHandle> {
  const context = options.audioContext;
  if (!context) throw new Error("speech detection needs an AudioContext");
  const config = { ...getDefaultRealTimeVADOptions("v5"), ...options };
  const model = await sources.load();
  let node: AudioWorkletNode | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let active = false;
  let destroyed = false;
  let frames: Float32Array[] = [];
  let processing: Promise<void> | null = null;
  const event = (value: FrameProcessorEvent): void => {
    if (destroyed) return;
    if (value.msg === Message.SpeechStart) void config.onSpeechStart();
    if (value.msg === Message.SpeechEnd) void config.onSpeechEnd(value.audio);
    if (value.msg === Message.VADMisfire) void config.onVADMisfire();
  };
  const processor = new FrameProcessor(model.process, model.reset_state, config, 32);
  const destroy = async (): Promise<void> => {
    if (destroyed) return;
    destroyed = true;
    active = false;
    frames = [];
    source?.disconnect();
    if (node) {
      node.port.onmessage = null;
      node.onprocessorerror = null;
      node.port.postMessage(Message.SpeechStop);
      node.disconnect();
    }
    await processing;
    await model.release();
  };
  try {
    node = await sources.worklet(context);
    source = context.createMediaStreamSource(await config.getStream());
    source.connect(node);
    const process = async (): Promise<void> => {
      try {
        while (active && !destroyed && frames.length) {
          const frame = frames.shift();
          if (frame) await processor.process(frame, event);
        }
      } catch (error) {
        active = false;
        frames = [];
        onerror(error);
      } finally {
        processing = null;
      }
    };
    node.port.onmessage = (message: MessageEvent<unknown>) => {
      if (!active || destroyed) return;
      const result = AudioFrame.safeParse(message.data);
      if (!result.success || result.data.data.byteLength !== 512 * 4) return;
      if (frames.length >= 64) {
        active = false;
        frames = [];
        onerror(new Error("speech detection cannot keep up on this device"));
        return;
      }
      frames.push(new Float32Array(result.data.data));
      processing ??= process();
    };
    node.onprocessorerror = () => {
      onerror(new Error("speech detection audio worklet failed"));
    };
    return {
      start: () => {
        if (destroyed) return Promise.reject(new Error("speech detector was released"));
        active = true;
        processor.resume();
        return Promise.resolve();
      },
      pause: async () => {
        active = false;
        frames = [];
        await processing;
        if (!destroyed) processor.pause(event);
      },
      destroy,
    };
  } catch (error) {
    await destroy();
    throw error;
  }
}
