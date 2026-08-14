import { afterEach, describe, expect, it, vi } from "vitest";
import { beginHandshake, discardGeneration, newOutputGate, paintIsCurrent } from "../lib/terminal";
import { TERMINAL_RETRY_MS, TerminalStream } from "./terminal.svelte.js";

class FakeSocket {
  static instances: FakeSocket[] = [];
  binaryType = "";
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  constructor() {
    FakeSocket.instances.push(this);
  }
  close(): void {
    /* the real socket is closed by the stream; we do not echo onclose */
  }
  send(): void {
    /* unused in this test */
  }
}

describe("TerminalStream retry", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    FakeSocket.instances = [];
  });

  it("invalidates an in-flight paint when the stream retries on its own timer", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);

    let gate = newOutputGate();
    let paintId = 0;
    const stream = new TerminalStream();
    stream.connect("att-1", {
      onHandshake() {
        gate = beginHandshake(gate, stream.generation);
        paintId = gate.paintId;
      },
      onBytes() {
        /* live bytes are not under test */
      },
      onUnavailable() {
        /* a 1000 close after handshake retries instead */
      },
      onGeneration(generation) {
        gate = discardGeneration(gate, generation);
      },
    });

    const first = FakeSocket.instances[0];
    if (!first?.onmessage || !first.onclose) throw new Error("expected a live socket");
    first.onmessage({ data: '{"cols":80,"rows":24}' });
    first.onmessage({ data: "screen" });
    expect(paintIsCurrent(gate, 1, paintId)).toBe(true);
    first.onclose({ code: 1000 });

    vi.advanceTimersByTime(TERMINAL_RETRY_MS);
    expect(FakeSocket.instances.length).toBe(2);
    expect(paintIsCurrent(gate, 1, paintId)).toBe(false);
  });
});
