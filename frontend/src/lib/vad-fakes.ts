/** Real segment boundaries with fake Silero scores and mic: tests need no audio hardware. */
import { FrameProcessor } from "@ricky0123/vad-web/dist/frame-processor";
import { Message } from "@ricky0123/vad-web/dist/messages";
import type { RealTimeVADOptions } from "@ricky0123/vad-web";
import type { VadHandle } from "./voice-listener";

export class FakeVad implements VadHandle {
  private probability = 0;
  readonly processor: FrameProcessor;
  destroyed = false;
  listening = false;
  constructor(readonly options: Partial<RealTimeVADOptions>) {
    this.processor = new FrameProcessor(
      () => Promise.resolve({ isSpeech: this.probability, notSpeech: 1 - this.probability }),
      () => undefined,
      {
        positiveSpeechThreshold: options.positiveSpeechThreshold ?? 0.3,
        negativeSpeechThreshold: options.negativeSpeechThreshold ?? 0.25,
        redemptionMs: options.redemptionMs ?? 1400,
        preSpeechPadMs: options.preSpeechPadMs ?? 300,
        minSpeechMs: options.minSpeechMs ?? 400,
        submitUserSpeechOnPause: options.submitUserSpeechOnPause ?? false,
      },
      32,
    );
  }
  private event = (
    event: Parameters<FrameProcessor["process"]>[1] extends (arg: infer E) => void ? E : never,
  ): void => {
    if (event.msg === Message.SpeechStart) void this.options.onSpeechStart?.();
    if (event.msg === Message.SpeechEnd) void this.options.onSpeechEnd?.(event.audio);
    if (event.msg === Message.VADMisfire) void this.options.onVADMisfire?.();
  };
  start(): Promise<void> {
    this.listening = true;
    this.processor.resume();
    return Promise.resolve();
  }
  pause(): Promise<void> {
    this.listening = false;
    this.processor.pause(this.event);
    return Promise.resolve();
  }
  destroy(): Promise<void> {
    this.destroyed = true;
    this.listening = false;
    return Promise.resolve();
  }
  async frames(probability: number, count: number, value = 0.1): Promise<void> {
    this.probability = probability;
    for (let i = 0; i < count; i++) {
      await this.processor.process(new Float32Array(512).fill(value), this.event);
    }
  }
}
