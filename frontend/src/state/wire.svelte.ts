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

import { buildChanged } from "../lib/build";
import { AUTH_REQUIRED_CLOSE, readAccessToken, recoverSocketAuthentication } from "../lib/http";
import type { SocketAuthPhase } from "../lib/http";
import { authenticatedSocketUrl } from "../lib/socket-auth";
import { decodeWireEvent, helloCommand } from "../lib/wire-commands";
import type { WireIdentity } from "../lib/wire-commands";
import { WireMessageCommandSchema, WireReattachCommandSchema, LegacyHelloSchema } from "../lib/contracts";
import type { HelloEvent, ReattachAction, WireEvent, WireMessageCommand } from "../lib/contracts";

export const GRACE_MS = 3000;
export const RETRY_MS = 1500;
export interface WireContext {
  wasReady: boolean;
  claimRejected: boolean;
  rejectClaim(): void;
}

export interface WireOutage {
  message: string;
  stopped: boolean;
}

export type WireEventHandler = (event: WireEvent, context: WireContext) => void;

/** Called when a handshake completes on a line this tab had already joined —
 *  i.e. after an outage, when whatever the tab believes may be out of date. */
export type WireResyncHandler = () => void;

/** Receives server identity after every successful handshake. Build identity
 * decides reload; metadata such as version must still refresh when it does not. */
export type WireHandshakeHandler = (hello: HelloEvent) => void;

/**
 * Could an unreadable frame just be an older server telling us to reload?
 *
 * Answers only that question, and only for a hello on this line. Anything else
 * unparseable is a genuine contract failure and must be reported as one.
 */
function staleBundle(data: unknown, convId: string): boolean {
  if (typeof data !== "string") return false;
  try {
    const hello = LegacyHelloSchema.parse(JSON.parse(data));
    return hello.conversation_id === convId && buildChanged(__PARTYLINE_BUILD__, hello.build);
  } catch {
    return false;
  }
}

class Wire {
  /** The handshake has completed and this socket may carry messages. */
  ready = $state(false);
  /** What to tell the user about the outage, or null while the wire is healthy. */
  outage = $state<WireOutage | null>(null);
  /** The server said it is going away. Nothing is coming back on its own. */
  stopped = $state(false);

  /**
   * The line whose handshake has already completed once.
   *
   * A *first* hello for a line follows `room.open()`, which has just fetched
   * everything. A *second* one is a reconnect, and the tab has been deaf for
   * however long the wire was down — which is exactly when the server rewrote
   * every attachment status during a restart. That difference is the only
   * thing this field exists to tell.
   */
  #handshakenFor: string | null = null;
  #generation = 0;
  #socket: WebSocket | null = null;
  #graceTimer: ReturnType<typeof setTimeout> | null = null;
  #retryTimer: ReturnType<typeof setTimeout> | null = null;
  #claimRejected = false;

  /** The live socket, for tests that need to drop or fake traffic on it. */
  get socket(): WebSocket | null {
    return this.#socket;
  }

  /**
   * Open the wire to a line, replacing whatever was open before.
   *
   * @param convId    the conversation to join
   * @param identity  the tab-scoped client id for reconnect takeover
   * @param onEvent   called with each server event, already parsed
   */
  connect(
    convId: string,
    identity: WireIdentity,
    onEvent: WireEventHandler,
    onResync: WireResyncHandler = () => undefined,
    onHandshake: WireHandshakeHandler = () => undefined,
    authenticationPhase: SocketAuthPhase = "initial",
  ): void {
    const generation = ++this.#generation;
    this.#teardown();
    this.ready = false;
    this.#claimRejected = false;

    const startedWith = readAccessToken();
    const socket = new WebSocket(authenticatedSocketUrl(`/ws/${convId}`, location, startedWith));
    this.#socket = socket;
    const current = (): boolean => generation === this.#generation;

    socket.onopen = () => {
      if (!current()) return;
      socket.send(JSON.stringify(helloCommand(identity)));
    };

    socket.onmessage = (event: MessageEvent<unknown>) => {
      if (!current()) return;
      let payload: WireEvent;
      try {
        payload = decodeWireEvent(event.data);
      } catch (failure: unknown) {
        // A frame this tab cannot parse is not a network problem, and must not
        // be reported as one. Every required field added to the wire makes an
        // older server unintelligible to a newer bundle — routine under
        // `npm run dev`, which proxies to whatever server happens to be up —
        // and without this the socket is fine, `ready` never arrives, and the
        // tab insists "the wire is down" forever while blaming the network.
        // Order matters. A tab whose bundle is merely old should reload into
        // the matching client rather than be told it is broken, so the stale
        // build is checked *before* the frame is declared unreadable.
        if (staleBundle(event.data, convId)) {
          location.reload();
          return;
        }
        this.reportIncompatible(failure);
        // Terminal for this socket, not merely terminal-looking. Closing alone
        // is not enough: already-queued or synthetic events would still pass
        // `current()`. Bumping the generation invalidates this handler the way
        // `disconnect()` does, so no later frame — even a well-formed one — can
        // move the badge or readiness on a connection we cannot understand.
        this.#generation++;
        this.#teardown();
        return;
      }

      if (payload.type === "hello" && payload.conversation_id === convId) {
        if (buildChanged(__PARTYLINE_BUILD__, payload.build)) {
          location.reload();
          return;
        }
        onHandshake(payload);
        authenticationPhase = "initial";
        this.stopped = false;
        this.ready = true;
        this.clearOutage();
        // Anything that happened while the wire was down reached no tab. The
        // server is the authority on what is true now, so ask it rather than
        // carrying on with a picture assembled before the outage.
        const reconnected = this.#handshakenFor === convId;
        this.#handshakenFor = convId;
        if (reconnected) onResync();
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
        /** Was the handshake ever granted? A refusal before it means the line
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

    socket.onclose = (event) => {
      if (!current() || this.#claimRejected) return;
      this.ready = false;
      if (event.code === AUTH_REQUIRED_CLOSE) {
        void recoverSocketAuthentication(startedWith, authenticationPhase)
          .then((recovery) => {
            if (current() && recovery.retry) {
              this.connect(convId, identity, onEvent, onResync, onHandshake, recovery.phase);
            }
          })
          .catch(() => {
            if (!current()) return;
            if (!this.stopped) this.#armOutage();
            this.#retryTimer = setTimeout(() => {
              if (current()) {
                this.connect(convId, identity, onEvent, onResync, onHandshake, authenticationPhase);
              }
            }, RETRY_MS);
          });
        return;
      }
      if (!this.stopped) this.#armOutage();
      this.#retryTimer = setTimeout(() => {
        if (current() && !this.#claimRejected) {
          this.connect(convId, identity, onEvent, onResync, onHandshake);
        }
      }, RETRY_MS);
    };
  }

  /** Send on the open wire. Returns false if there is nothing to send on. */
  send(payload: WireMessageCommand): boolean {
    if (!this.ready || this.#socket?.readyState !== WebSocket.OPEN) return false;
    this.#socket.send(JSON.stringify(WireMessageCommandSchema.parse(payload)));
    return true;
  }

  /** Accept or cancel the exact same-line offer reported by the server. */
  chooseReattach(token: string, action: ReattachAction): boolean {
    if (!this.ready || this.#socket?.readyState !== WebSocket.OPEN) return false;
    const command = WireReattachCommandSchema.parse({ type: "reattach", token, action });
    this.#socket.send(JSON.stringify(command));
    return true;
  }

  /** Close for good: leaving the app, or losing the line we were on. */
  disconnect(): void {
    this.#handshakenFor = null;
    this.#generation++;
    this.#teardown();
    this.ready = false;
    this.#claimRejected = false;
  }

  /** Say that the server is speaking a protocol this document does not know. */
  reportIncompatible(failure: unknown): void {
    if (this.#graceTimer) clearTimeout(this.#graceTimer);
    this.#graceTimer = null;
    this.ready = false;
    // `stopped` suppresses the reconnect timer and the "reconnecting…" banner;
    // retrying cannot help, since the server will not become compatible by
    // being asked again.
    this.stopped = true;
    this.outage = {
      // Names what is true — the two sides disagree about the protocol —
      // rather than guessing which side is wrong. "This tab is out of date"
      // would be a diagnosis, and a wrong one whenever the server is the stale
      // party or the mismatch is a defect: reloading would then reproduce it
      // forever while sounding like a fix.
      message: "client/server protocol mismatch — reload a matching build to continue",
      stopped: true,
    };
    console.error("partyline: unreadable frame from the server", failure);
  }

  reportStopped(): void {
    this.stopped = true;
    this.ready = false;
    if (this.#graceTimer !== null) clearTimeout(this.#graceTimer);
    this.#graceTimer = null;
    this.outage = { message: "partyline has stopped — waiting for a restart…", stopped: true };
  }

  clearOutage(): void {
    if (this.#graceTimer !== null) clearTimeout(this.#graceTimer);
    this.#graceTimer = null;
    if (!this.stopped) this.outage = null;
  }

  #armOutage(): void {
    if (this.#graceTimer || this.outage) return;
    this.#graceTimer = setTimeout(() => {
      this.#graceTimer = null;
      this.outage = { message: "the wire is down — reconnecting…", stopped: false };
    }, GRACE_MS);
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

export const wire = new Wire();
