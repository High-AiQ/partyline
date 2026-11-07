/** Bounded transcription pipeline. Completion may be out of order; sending never is. */
export function spokenAction(text: string): { text: string; scratch: boolean } {
  const clean = text.trim();
  const normalized = clean
    .toLowerCase()
    .replace(/[.,!?;:]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  const scratch = /^scratch that(?:\b|$)/i.test(normalized);
  if (normalized === "cancel" || normalized === "scratch that") return { text: "", scratch };
  const words = scratch ? clean.replace(/^scratch\s+that\b[\s.,!?;:]*/i, "").trim() : clean;
  const filler = words
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, "")
    .trim();
  return { text: !filler || /^(?:(?:u+m+|u+h+|e+r+m*|h+m+|a+h+)[\s]*)+$/.test(filler) ? "" : words, scratch };
}

interface Take {
  audio: Blob | null;
  controller: AbortController;
  text: string | null;
  cancelled: boolean;
  sending: boolean;
}
export interface HandsFreeQueueHooks {
  transcribe: (audio: Blob, signal: AbortSignal) => Promise<string>;
  send: (text: string) => Promise<boolean>;
  onsent: (text: string) => void;
  onerror: (message: string) => void;
  onpending: (count: number) => void;
}
export class HandsFreeQueue {
  private takes: Take[] = [];
  private running = 0;
  private sending = false;
  private closed = false;

  constructor(private hooks: HandsFreeQueueHooks) {}

  add(audio: Blob): void {
    if (this.isClosed()) return;
    if (this.takes.length >= 8) {
      this.hooks.onerror("Voice queue is full; this take was discarded. Please pause for transcription.");
      return;
    }
    this.takes.push({
      audio,
      controller: new AbortController(),
      text: null,
      cancelled: false,
      sending: false,
    });
    this.changed();
    this.pump();
  }

  dispose(): void {
    this.closed = true;
    for (const take of this.takes) take.controller.abort();
    this.takes = [];
    this.changed();
  }

  private isClosed(): boolean {
    return this.closed;
  }

  private changed(): void {
    this.hooks.onpending(this.takes.length);
  }

  private pump(): void {
    if (this.isClosed()) return;
    // Two requests allow a spoken correction to overtake an unsent transcript.
    for (const take of this.takes) {
      if (this.running >= 2) break;
      if (!take.audio || take.cancelled) continue;
      const audio = take.audio;
      take.audio = null;
      this.running++;
      void this.recognize(take, audio);
    }
  }

  private async recognize(take: Take, audio: Blob): Promise<void> {
    try {
      const transcript = await this.hooks.transcribe(audio, take.controller.signal);
      if (this.isClosed() || take.cancelled) return;
      const action = spokenAction(transcript);
      if (action.scratch) {
        const previous = this.takes[this.takes.indexOf(take) - 1];
        if (previous && !previous.sending) {
          previous.cancelled = true;
          previous.audio = null;
          previous.controller.abort();
        }
      }
      take.text = action.text;
    } catch (error) {
      if (!this.isClosed() && !take.cancelled) {
        take.text = "";
        this.hooks.onerror(error instanceof Error ? error.message : "could not transcribe speech");
      }
    } finally {
      this.running--;
      if (!this.isClosed()) {
        void this.flush();
        this.pump();
      }
    }
  }

  private async flush(): Promise<void> {
    if (this.sending || this.isClosed()) return;
    this.sending = true;
    try {
      while (!this.isClosed()) {
        const take = this.takes[0];
        if (!take || (!take.cancelled && take.text === null)) break;
        if (!take.cancelled && take.text) {
          take.sending = true; // once handed to the transport, speech cannot retract it
          const text = take.text;
          try {
            if (await this.hooks.send(text)) {
              if (!this.isClosed()) this.hooks.onsent(text);
            } else if (!this.isClosed()) this.hooks.onerror(`Voice message was not sent: ${text}`);
          } catch {
            if (!this.isClosed()) this.hooks.onerror(`Voice message was not sent: ${text}`);
          }
        }
        if (this.isClosed()) break;
        this.takes.shift();
        this.changed();
      }
    } finally {
      this.sending = false;
    }
  }
}
