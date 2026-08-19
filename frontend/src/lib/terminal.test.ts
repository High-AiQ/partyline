import { describe, expect, it } from "vitest";
import {
  beginHandshake,
  discardGeneration,
  emptyHeldBytes,
  holdLiveBytes,
  isNotLiveClose,
  LIVE_HOLD_LIMIT,
  newFrameReader,
  newOutputGate,
  openLive,
  paintIsCurrent,
  readBinaryFrame,
  readTextFrame,
  receiveOutputBytes,
  shouldRetryClose,
  takeLiveBytes,
  terminalSocketUrl,
} from "./terminal";

describe("terminalSocketUrl", () => {
  it("uses wss on https and includes the attachment id", () => {
    expect(terminalSocketUrl("att-1", { protocol: "https:", host: "example.test" })).toBe(
      "wss://example.test/ws/attachments/att-1/terminal",
    );
  });

  it("authenticates the terminal socket with an encoded access token", () => {
    expect(terminalSocketUrl("att-1", { protocol: "https:", host: "example.test" }, "jwt+/=")).toBe(
      "wss://example.test/ws/attachments/att-1/terminal?token=jwt%2B%2F%3D",
    );
  });

  it("uses ws on http", () => {
    expect(terminalSocketUrl("att-1", { protocol: "http:", host: "127.0.0.1:8642" })).toBe(
      "ws://127.0.0.1:8642/ws/attachments/att-1/terminal",
    );
  });
});

describe("isNotLiveClose", () => {
  it("treats 4404 as not-live and other codes as resync", () => {
    expect(isNotLiveClose(4404)).toBe(true);
    expect(isNotLiveClose(1000)).toBe(false);
  });
});

describe("shouldRetryClose", () => {
  it("does not retry 4404 or a close before the handshake", () => {
    expect(shouldRetryClose(4404, true)).toBe(false);
    expect(shouldRetryClose(1006, false)).toBe(false);
    expect(shouldRetryClose(1000, false)).toBe(false);
  });

  it("retries an ordinary close after a handshake so the client can resync", () => {
    expect(shouldRetryClose(1000, true)).toBe(true);
    expect(shouldRetryClose(1006, true)).toBe(true);
  });
});

describe("readTextFrame", () => {
  it("parses geometry then yields a snapshot handshake", () => {
    const geometry = readTextFrame(newFrameReader(), '{"cols":120,"rows":40}');
    expect(geometry.ok).toBe(true);
    if (!geometry.ok) return;
    const snapshot = readTextFrame(geometry.reader, "hello\nworld");
    expect(snapshot).toEqual({
      ok: true,
      reader: { phase: "live" },
      handshake: { geometry: { cols: 120, rows: 40 }, snapshot: "hello\nworld" },
    });
  });

  it("rejects a geometry frame that is not the named contract", () => {
    expect(readTextFrame(newFrameReader(), '{"cols":0,"rows":40}')).toEqual({
      ok: false,
      error: "invalid terminal geometry frame",
    });
    expect(readTextFrame(newFrameReader(), "not-json")).toEqual({
      ok: false,
      error: "invalid terminal geometry frame",
    });
  });

  it("rejects a stray text frame after the handshake", () => {
    const geometry = readTextFrame(newFrameReader(), '{"cols":80,"rows":24}');
    if (!geometry.ok) throw new Error("expected geometry");
    const live = readTextFrame(geometry.reader, "screen");
    if (!live.ok) throw new Error("expected snapshot");
    expect(readTextFrame(live.reader, "extra")).toEqual({
      ok: false,
      error: "unexpected text frame after handshake",
    });
  });
});

describe("readBinaryFrame", () => {
  it("returns bytes only after the handshake", () => {
    const raw = new Uint8Array([0x1b, 0x5b, 0x41]).buffer;
    expect(readBinaryFrame(newFrameReader(), raw)).toBeNull();
    const geometry = readTextFrame(newFrameReader(), '{"cols":80,"rows":24}');
    if (!geometry.ok) throw new Error("expected geometry");
    expect(readBinaryFrame(geometry.reader, raw)).toBeNull();
    const live = readTextFrame(geometry.reader, "");
    if (!live.ok) throw new Error("expected snapshot");
    expect(readBinaryFrame(live.reader, raw)).toEqual(new Uint8Array([0x1b, 0x5b, 0x41]));
  });
});

describe("holdLiveBytes", () => {
  it("keeps arrival order for the current generation", () => {
    const first = new Uint8Array([1]);
    const second = new Uint8Array([2]);
    const held = holdLiveBytes(holdLiveBytes(emptyHeldBytes(3), 3, first).held, 3, second).held;
    expect(takeLiveBytes(held, 3)).toEqual({
      held: { generation: 3, chunks: [] },
      chunks: [first, second],
    });
  });

  it("drops a stale hold when the generation changes", () => {
    const stale = holdLiveBytes(emptyHeldBytes(1), 1, new Uint8Array([9])).held;
    const live = holdLiveBytes(stale, 2, new Uint8Array([7])).held;
    expect(takeLiveBytes(live, 2).chunks).toEqual([new Uint8Array([7])]);
    expect(takeLiveBytes(stale, 2)).toEqual({
      held: { generation: 2, chunks: [] },
      chunks: [],
    });
  });

  it("overflows at the server queue bound and empties the hold", () => {
    let held = emptyHeldBytes(1);
    for (let i = 0; i < LIVE_HOLD_LIMIT; i++) {
      const next = holdLiveBytes(held, 1, new Uint8Array([i]));
      expect(next.overflow).toBe(false);
      held = next.held;
    }
    expect(holdLiveBytes(held, 1, new Uint8Array([255]))).toEqual({
      overflow: true,
      held: { generation: 1, chunks: [] },
    });
  });
});

describe("output gate ordering", () => {
  it("holds bytes until the matching paint opens, then writes live", () => {
    let gate = beginHandshake(newOutputGate(), 1);
    const paintId = gate.paintId;
    const first = new Uint8Array([0x1b]);
    const second = new Uint8Array([0x41]);
    gate = receiveOutputBytes(gate, 1, first).gate;
    gate = receiveOutputBytes(gate, 1, second).gate;
    expect(paintIsCurrent(gate, 1, paintId)).toBe(true);
    const opened = openLive(gate, 1, paintId);
    expect(opened.chunks).toEqual([first, second]);
    const live = receiveOutputBytes(opened.gate, 1, new Uint8Array([0x42]));
    expect(live.write).toEqual(new Uint8Array([0x42]));
    expect(live.overflow).toBe(false);
  });

  it("invalidates an in-flight paint when overflow forces a reconnect", () => {
    let gate = beginHandshake(newOutputGate(), 1);
    const paintId = gate.paintId;
    for (let i = 0; i < LIVE_HOLD_LIMIT; i++) {
      gate = receiveOutputBytes(gate, 1, new Uint8Array([i])).gate;
    }
    const overflowed = receiveOutputBytes(gate, 1, new Uint8Array([255]));
    expect(overflowed.overflow).toBe(true);
    gate = discardGeneration(overflowed.gate, 2);
    expect(paintIsCurrent(gate, 1, paintId)).toBe(false);
    expect(openLive(gate, 1, paintId).chunks).toEqual([]);
  });

  it("discards an in-flight paint and its buffer when the generation changes", () => {
    let gate = beginHandshake(newOutputGate(), 1);
    const staleId = gate.paintId;
    gate = receiveOutputBytes(gate, 1, new Uint8Array([9])).gate;
    gate = discardGeneration(gate, 2);
    expect(paintIsCurrent(gate, 1, staleId)).toBe(false);
    expect(openLive(gate, 1, staleId).chunks).toEqual([]);
    gate = beginHandshake(gate, 2);
    const fresh = new Uint8Array([7]);
    gate = receiveOutputBytes(gate, 2, fresh).gate;
    expect(openLive(gate, 2, gate.paintId).chunks).toEqual([fresh]);
  });
});
