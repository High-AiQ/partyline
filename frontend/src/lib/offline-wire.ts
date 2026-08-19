/** Send one message to a line without replacing the line currently open. */

import { WireMessageCommandSchema } from "./contracts";
import { AUTH_REQUIRED_CLOSE, readAccessToken, recoverSocketAuthentication } from "./http";
import type { SocketAuthPhase } from "./http";
import { authenticatedSocketUrl } from "./socket-auth";
import { decodeWireEvent, helloCommand } from "./wire-commands";
import type { WireIdentity } from "./wire-commands";

const HELLO_TIMEOUT_MS = 4000;

class SocketAuthenticationError extends Error {}

export async function sendOffLine(convId: string, identity: WireIdentity, body: string): Promise<void> {
  let phase: SocketAuthPhase = "initial";
  for (;;) {
    const startedWith = readAccessToken();
    try {
      await sendAttempt(convId, identity, body, startedWith);
      return;
    } catch (failure: unknown) {
      if (!(failure instanceof SocketAuthenticationError)) throw failure;
      const recovery = await recoverSocketAuthentication(startedWith, phase);
      if (!recovery.retry) {
        throw new Error("authentication required — sign in again", { cause: failure });
      }
      phase = recovery.phase;
    }
  }
}

function sendAttempt(
  convId: string,
  identity: WireIdentity,
  body: string,
  accessToken: string | null,
): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const socket = new WebSocket(authenticatedSocketUrl(`/ws/${convId}`, location, accessToken));
    let settled = false;
    const finish = (error?: Error): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      try {
        socket.close();
      } catch {
        /* already gone */
      }
      if (error) reject(error);
      else resolve();
    };
    const timeout = setTimeout(() => {
      finish(new Error("line is not reachable"));
    }, HELLO_TIMEOUT_MS);

    socket.onopen = () => {
      socket.send(JSON.stringify(helloCommand(identity)));
    };
    socket.onmessage = (event: MessageEvent<unknown>) => {
      const payload = decodeWireEvent(event.data);
      if (payload.type === "error") {
        finish(new Error(payload.message || "could not claim this line"));
        return;
      }
      if (payload.type !== "hello") return;
      socket.send(JSON.stringify(WireMessageCommandSchema.parse({ body })));
      setTimeout(() => {
        finish();
      }, 100);
    };
    socket.onclose = (event) => {
      finish(
        event.code === AUTH_REQUIRED_CLOSE
          ? new SocketAuthenticationError()
          : new Error("line is not reachable"),
      );
    };
    // Browsers may emit `error` before the close event that carries the useful
    // 4401 code. Let `close` classify it so an expired token can still refresh.
    socket.onerror = () => undefined;
  });
}
