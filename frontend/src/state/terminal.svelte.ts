/**
 * The peek terminal socket: one attachment, generation-guarded reconnect.
 *
 * Closing is the designed recovery path. The server ends the socket when the
 * process exits or a viewer overruns its queue; we reconnect and re-render
 * from a fresh geometry-plus-snapshot handshake. 4404 after accept means the
 * attachment is not live — that one does not retry.
 *
 * Stale handlers from a replaced socket are dropped the same way the room
 * wire does: bump a generation, check it in every callback.
 */

import {
  newFrameReader,
  readBinaryFrame,
  readTextFrame,
  shouldRetryClose,
  terminalSocketUrl,
} from "../lib/terminal";
import type { FrameReader, TerminalHandshake } from "../lib/terminal";

export const TERMINAL_RETRY_MS = 1500;

export interface TerminalHandlers {
  onHandshake(next: TerminalHandshake): void;
  onBytes(data: Uint8Array): void;
  onUnavailable(): void;
  /** Fired synchronously after every generation bump in `connect()`. */
  onGeneration(generation: number): void;
}

export class TerminalStream {
  generation = $state(0);
  unavailable = $state(false);

  #socket: WebSocket | null = null;
  #retryTimer: ReturnType<typeof setTimeout> | null = null;

  connect(attId: string, handlers: TerminalHandlers): number {
    const generation = ++this.generation;
    handlers.onGeneration(generation);
    this.#teardown();
    this.unavailable = false;

    const socket = new WebSocket(terminalSocketUrl(attId, location));
    socket.binaryType = "arraybuffer";
    this.#socket = socket;
    let reader: FrameReader = newFrameReader();
    let handshaken = false;
    const current = (): boolean => generation === this.generation;

    socket.onmessage = (event: MessageEvent<unknown>) => {
      if (!current()) return;
      if (typeof event.data === "string") {
        const next = readTextFrame(reader, event.data);
        if (!next.ok) return;
        reader = next.reader;
        if (next.handshake) {
          handshaken = true;
          handlers.onHandshake(next.handshake);
        }
        return;
      }
      if (event.data instanceof ArrayBuffer) {
        const bytes = readBinaryFrame(reader, event.data);
        if (bytes) handlers.onBytes(bytes);
      }
    };

    socket.onclose = (event: CloseEvent) => {
      if (!current()) return;
      this.#socket = null;
      if (!shouldRetryClose(event.code, handshaken)) {
        this.unavailable = true;
        handlers.onUnavailable();
        return;
      }
      this.#retryTimer = setTimeout(() => {
        if (current()) this.connect(attId, handlers);
      }, TERMINAL_RETRY_MS);
    };
    return generation;
  }

  send(data: string): boolean {
    if (this.#socket?.readyState !== WebSocket.OPEN) return false;
    this.#socket.send(data);
    return true;
  }

  disconnect(): void {
    this.generation++;
    this.#teardown();
    this.unavailable = false;
  }

  #teardown(): void {
    if (this.#retryTimer !== null) clearTimeout(this.#retryTimer);
    this.#retryTimer = null;
    if (this.#socket) {
      try {
        this.#socket.close();
      } catch {
        /* already gone */
      }
      this.#socket = null;
    }
  }
}
