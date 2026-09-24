import { afterEach, describe, expect, it, vi } from "vitest";
import { wire, WAKE_VERIFY_MS } from "./wire.svelte.js";

class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState: number = WebSocket.OPEN;
  readonly sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  close(): void {
    this.readyState = WebSocket.CLOSED;
  }

  send(data: string): void {
    this.sent.push(data);
  }
}

afterEach(() => {
  wire.disconnect();
  FakeSocket.instances = [];
  vi.unstubAllGlobals();
});

describe("wire send recovery", () => {
  it("reconnects immediately when send finds the wire down", () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.stubGlobal("location", { protocol: "http:", host: "127.0.0.1:8642" });
    wire.connect("line", { clientId: "tab" }, () => undefined);
    const first = FakeSocket.instances[0];
    if (!first?.onopen || !first.onmessage) throw new Error("missing socket handlers");
    first.onopen();
    first.onmessage({
      data: JSON.stringify({
        type: "hello",
        conversation_id: "line",
        handle: "greg",
        build: __PARTYLINE_BUILD__,
        version: "2.11.1",
        instance_name: null,
      }),
    });
    expect(wire.ready).toBe(true);

    first.close();
    wire.ready = false;
    const before = FakeSocket.instances.length;
    expect(wire.send({ body: "hello" })).toBe(false);
    expect(FakeSocket.instances.length).toBeGreaterThan(before);
  });

  it("replaces a stale socket after the tab was hidden long enough", () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.stubGlobal("location", { protocol: "http:", host: "127.0.0.1:8642" });
    wire.connect("line", { clientId: "tab" }, () => undefined);
    const first = FakeSocket.instances[0];
    if (!first?.onopen || !first.onmessage) throw new Error("missing socket handlers");
    first.onopen();
    first.onmessage({
      data: JSON.stringify({
        type: "hello",
        conversation_id: "line",
        handle: "greg",
        build: __PARTYLINE_BUILD__,
        version: "2.11.1",
        instance_name: null,
      }),
    });

    const hiddenAt = 1_000;
    vi.spyOn(Date, "now").mockReturnValueOnce(hiddenAt);
    wire.noteHidden();
    const before = FakeSocket.instances.length;
    vi.spyOn(Date, "now").mockReturnValue(hiddenAt + WAKE_VERIFY_MS + 1);
    wire.verifyOnWake();

    expect(FakeSocket.instances.length).toBeGreaterThan(before);
  });
});
