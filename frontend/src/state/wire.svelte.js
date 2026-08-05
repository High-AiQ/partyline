/**
 * The wire: one WebSocket to one line, and an honest account of its health.
 *
 * Two rules here are load-bearing and were both learned the hard way.
 *
 * **The generation guard.** Switching lines closes a socket and opens another,
 * but `close` is asynchronous and the old socket's handlers keep firing after
 * the new one exists. Every handler therefore checks the generation it was
 * created in against the current one, and a stale socket's events are dropped
 * on the floor. Without it, leaving a line and coming back replays the old
 * line's traffic into the new one's feed.
 *
 * **The grace period.** The socket retries forever, which is right, but it used
 * to do it silently — a crashed server, a scheduled restart and a slow network
 * all looked identical, which is to say they all looked like nothing. The
 * banner appears only once the wire has stayed down for `GRACE_MS`, and a
 * successful reconnect cancels it. Counting drops instead would make the banner
 * depend on how many times the socket happened to bounce, which is not
 * something the user did anything to cause.
 *
 * **Build identity.** The production bundle contains its own deterministic
 * build id. A successful hello reports the server's id atomically with the
 * socket handshake. If they differ, this tab is old and reloads; an ordinary
 * reconnect stays on the page and keeps everything in place.
 */

import { buildChanged } from "../lib/build.js";

export const GRACE_MS = 3000;
export const RETRY_MS = 1500;
const HELLO_TIMEOUT_MS = 4000;

export const socketUrl = (convId, loc = location) =>
  (loc.protocol === "https:" ? "wss://" : "ws://") + loc.host + "/ws/" + convId;

class Wire {
  /** The handshake has completed and this socket may carry messages. */
  ready = $state(false);
  /** What to tell the user about the outage, or null while the wire is healthy. */
  outage = $state(null);
  /** The server said it is going away. Nothing is coming back on its own. */
  stopped = $state(false);

  #generation = 0;
  #socket = null;
  #graceTimer = null;
  #retryTimer = null;
  #claimRejected = false;

  /** The live socket, for tests that need to drop or fake traffic on it. */
  get socket() {
    return this.#socket;
  }

  /**
   * Open the wire to a line, replacing whatever was open before.
   *
   * @param convId    the conversation to join
   * @param identity  `{handle, clientId}` for the hello handshake
   * @param onEvent   called with each server event, already parsed
   */
  connect(convId, identity, onEvent) {
    const generation = ++this.#generation;
    this.#teardown();
    this.ready = false;
    this.#claimRejected = false;

    const socket = new WebSocket(socketUrl(convId));
    this.#socket = socket;
    const current = () => generation === this.#generation;

    socket.onopen = () => {
      if (!current()) return;
      socket.send(JSON.stringify({ type: "hello", handle: identity.handle, client_id: identity.clientId }));
    };

    socket.onmessage = (event) => {
      if (!current()) return;
      const payload = JSON.parse(event.data);

      if (payload.type === "hello" && payload.conversation_id === convId) {
        if (buildChanged(__PARTYLINE_BUILD__, payload.build)) {
          location.reload();
          return;
        }
        this.stopped = false;
        this.ready = true;
        this.clearOutage();
        return;
      }
      if (payload.type === "shutdown") {
        this.reportStopped();
        try {
          socket.close();
        } catch {
          /* already gone */
        }
        return;
      }
      onEvent(payload, {
        /** Was the handshake ever granted? A refusal before it means the handle
         *  was rejected; after it means the line went away underneath us. */
        wasReady: this.ready,
        claimRejected: this.#claimRejected,
        rejectClaim: () => {
          this.#claimRejected = true;
          this.ready = false;
          try {
            socket.close();
          } catch {
            /* already gone */
          }
        },
      });
    };

    socket.onclose = () => {
      if (!current() || this.#claimRejected) return;
      this.ready = false;
      if (!this.stopped) this.#armOutage();
      this.#retryTimer = setTimeout(() => {
        if (current() && !this.#claimRejected) this.connect(convId, identity, onEvent);
      }, RETRY_MS);
    };
  }

  /** Send on the open wire. Returns false if there is nothing to send on. */
  send(payload) {
    if (!this.ready || this.#socket?.readyState !== WebSocket.OPEN) return false;
    this.#socket.send(JSON.stringify(payload));
    return true;
  }

  /** Close for good: leaving the app, or losing the line we were on. */
  disconnect() {
    this.#generation++;
    this.#teardown();
    this.ready = false;
    this.#claimRejected = false;
  }

  reportStopped() {
    this.stopped = true;
    this.ready = false;
    clearTimeout(this.#graceTimer);
    this.#graceTimer = null;
    this.outage = { message: "partyline has stopped — waiting for a restart…", stopped: true };
  }

  clearOutage() {
    clearTimeout(this.#graceTimer);
    this.#graceTimer = null;
    if (!this.stopped) this.outage = null;
  }

  #armOutage() {
    if (this.#graceTimer || this.outage) return;
    this.#graceTimer = setTimeout(() => {
      this.#graceTimer = null;
      this.outage = { message: "the wire is down — reconnecting…", stopped: false };
    }, GRACE_MS);
  }

  #teardown() {
    clearTimeout(this.#retryTimer);
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

export const wire = new Wire();

/**
 * Post one message to a line without joining it.
 *
 * This exists for "warn processes first" in the delete dialog: you can delete a
 * line you are not currently on, and the warning has to reach it anyway. It
 * opens its own short-lived socket, completes the handshake, sends, and hangs
 * up — deliberately not touching the shared wire, which is still holding the
 * line the user is actually looking at.
 */
export function sendOffLine(convId, identity, body) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(socketUrl(convId));
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      try {
        socket.close();
      } catch {
        /* already gone */
      }
      error ? reject(error) : resolve();
    };
    const timeout = setTimeout(() => finish(new Error("line is not reachable")), HELLO_TIMEOUT_MS);

    socket.onopen = () => {
      socket.send(JSON.stringify({ type: "hello", handle: identity.handle, client_id: identity.clientId }));
    };
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "error") return finish(new Error(payload.message || "could not claim this line"));
      if (payload.type !== "hello") return;
      socket.send(JSON.stringify({ sender: identity.handle, body }));
      // Give the frame a moment to leave before hanging up on ourselves.
      setTimeout(() => finish(), 100);
    };
    socket.onerror = () => finish(new Error("line is not reachable"));
  });
}
