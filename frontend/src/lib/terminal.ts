/** Wire rules for the live terminal peek socket. */

import { z } from "zod";

export const NOT_LIVE_CLOSE = 4404;

export const TerminalGeometrySchema = z.object({
  cols: z.number().int().positive(),
  rows: z.number().int().positive(),
});
export type TerminalGeometry = z.infer<typeof TerminalGeometrySchema>;

export interface SocketLocation {
  protocol: string;
  host: string;
}

export interface TerminalHandshake {
  geometry: TerminalGeometry;
  snapshot: string;
}

export type FrameReader =
  { phase: "geometry" } | { phase: "snapshot"; geometry: TerminalGeometry } | { phase: "live" };

export type TextFrameResult =
  { ok: true; reader: FrameReader; handshake?: TerminalHandshake } | { ok: false; error: string };

export const newFrameReader = (): FrameReader => ({ phase: "geometry" });

export const isNotLiveClose = (code: number): boolean => code === NOT_LIVE_CLOSE;

/** Resync only after a completed handshake. A close before geometry is
 *  "not live" (or a lost 4404) — retrying would spin on a dead attachment. */
export const shouldRetryClose = (code: number, handshaken: boolean): boolean =>
  handshaken && !isNotLiveClose(code);

export const terminalSocketUrl = (attId: string, loc: SocketLocation): string =>
  (loc.protocol === "https:" ? "wss://" : "ws://") + loc.host + "/ws/attachments/" + attId + "/terminal";

/** First text frame is geometry JSON; the second is the pyte snapshot. */
export function readTextFrame(reader: FrameReader, text: string): TextFrameResult {
  if (reader.phase === "geometry") {
    try {
      const decoded: unknown = JSON.parse(text);
      const geometry = TerminalGeometrySchema.parse(decoded);
      return { ok: true, reader: { phase: "snapshot", geometry } };
    } catch {
      return { ok: false, error: "invalid terminal geometry frame" };
    }
  }
  if (reader.phase === "snapshot") {
    return {
      ok: true,
      reader: { phase: "live" },
      handshake: { geometry: reader.geometry, snapshot: text },
    };
  }
  return { ok: false, error: "unexpected text frame after handshake" };
}

/** Binary frames are raw pty bytes and only apply after the handshake. */
export function readBinaryFrame(reader: FrameReader, data: ArrayBuffer): Uint8Array | null {
  if (reader.phase !== "live") return null;
  return new Uint8Array(data);
}

/** Bytes that arrived while the emulator was still opening. Tagged by the
 *  socket generation so a stale hold cannot flush into a newer terminal. */
export interface HeldBytes {
  generation: number;
  chunks: Uint8Array[];
}

export const emptyHeldBytes = (generation: number): HeldBytes => ({ generation, chunks: [] });

/** Same bound as the server viewer queue. Overflow must resync, not drop a hole. */
export const LIVE_HOLD_LIMIT = 32;

export interface HoldResult {
  overflow: boolean;
  held: HeldBytes;
}

export function holdLiveBytes(held: HeldBytes, generation: number, data: Uint8Array): HoldResult {
  if (held.generation !== generation) {
    return { overflow: false, held: { generation, chunks: [data] } };
  }
  if (held.chunks.length >= LIVE_HOLD_LIMIT) {
    return { overflow: true, held: emptyHeldBytes(generation) };
  }
  const chunks = held.chunks.slice();
  chunks.push(data);
  return { overflow: false, held: { generation, chunks } };
}

export function takeLiveBytes(
  held: HeldBytes,
  generation: number,
): { held: HeldBytes; chunks: Uint8Array[] } {
  if (held.generation !== generation) return { held: emptyHeldBytes(generation), chunks: [] };
  return { held: emptyHeldBytes(generation), chunks: held.chunks };
}

/** Component-side handoff: which paint may write, and where live bytes go. */
export interface OutputGate {
  generation: number;
  paintId: number;
  live: boolean;
  held: HeldBytes;
}

export const newOutputGate = (): OutputGate => ({
  generation: 0,
  paintId: 0,
  live: false,
  held: emptyHeldBytes(0),
});

export function beginHandshake(gate: OutputGate, generation: number): OutputGate {
  return {
    generation,
    paintId: gate.paintId + 1,
    live: false,
    held: emptyHeldBytes(generation),
  };
}

export function discardGeneration(gate: OutputGate, generation: number): OutputGate {
  return {
    generation,
    paintId: gate.paintId + 1,
    live: false,
    held: emptyHeldBytes(generation),
  };
}

export const paintIsCurrent = (gate: OutputGate, generation: number, paintId: number): boolean =>
  gate.generation === generation && gate.paintId === paintId;

export function receiveOutputBytes(
  gate: OutputGate,
  generation: number,
  data: Uint8Array,
): { gate: OutputGate; write: Uint8Array | null; overflow: boolean } {
  if (gate.live && gate.generation === generation) {
    return { gate, write: data, overflow: false };
  }
  const held = holdLiveBytes(gate.held, generation, data);
  return {
    gate: { ...gate, live: false, held: held.held },
    write: null,
    overflow: held.overflow,
  };
}

export function openLive(
  gate: OutputGate,
  generation: number,
  paintId: number,
): { gate: OutputGate; chunks: Uint8Array[] } {
  if (!paintIsCurrent(gate, generation, paintId)) return { gate, chunks: [] };
  const taken = takeLiveBytes(gate.held, generation);
  return { gate: { ...gate, held: taken.held, live: true }, chunks: taken.chunks };
}
