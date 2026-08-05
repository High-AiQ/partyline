/**
 * The room: the list of lines, the line you are on, and everything on it.
 *
 * This is the one place that turns a server event into a change on screen, so
 * the components below it can be dumb about ordering, deduplication and
 * reconnects. Two guards run through it:
 *
 *   - **`#epoch`** rises on every line change, and any `await` that resolves
 *     after it moved is discarded. Clicking two lines quickly used to let the
 *     slower fetch land last and paint the wrong line's history.
 *   - **`#seen`** holds message ids, because a reconnect replays history and
 *     the same message will arrive twice.
 */

import { SvelteSet } from "svelte/reactivity";
import { api } from "../lib/api.js";
import { session } from "./session.svelte.js";
import { wire, sendOffLine } from "./wire.svelte.js";
import { clearConversationRoute, routedConversationId, setConversationRoute } from "../lib/routing.js";
import { isLive } from "../lib/attachments.js";

class Room {
  conversations = $state([]);
  archived = $state([]);
  archiveOpen = $state(false);

  conversation = $state(null);
  messages = $state([]);
  attachments = $state([]);

  /** Handles seen speaking here, for the @ autocomplete. Not persisted: it is a
   *  convenience, and the server is the authority on who may be mentioned.
   *  `SvelteSet`, not `Set`: the deep proxy does not see through a native Set's
   *  internals, so `.add()` on one would update nothing on screen. */
  humans = new SvelteSet();
  /** Attachments blocked on a dialog, which the board rings until someone peeks. */
  attention = new SvelteSet();

  /** A transient toast, distinct from the wire banner: this one goes away. */
  notice = $state(null);

  #seen = new Set();
  #epoch = 0;
  #noticeTimer = null;

  get identity() {
    return { handle: session.handle, clientId: session.clientId };
  }

  // ── the list ───────────────────────────────────────────────────────────
  async loadConversations() {
    this.conversations = await api.conversations();
    // Arriving on a deep link: the route named a line before the list existed.
    const routedId = routedConversationId();
    if (!routedId) return;
    const routed = this.conversations.find((c) => c.id === routedId);
    if (routed && this.conversation?.id !== routed.id) this.open(routed, { fromRoute: true });
  }

  async loadArchived() {
    this.archived = await api.conversations(true);
  }

  refreshArchiveIfOpen() {
    if (this.archiveOpen) this.loadArchived().catch(() => {});
  }

  async createConversation(name) {
    const created = await api.createConversation(name);
    await this.loadConversations();
    this.open(created);
  }

  // ── the line you are on ────────────────────────────────────────────────
  async open(conversation, { fromRoute = false } = {}) {
    const epoch = ++this.#epoch;
    if (!fromRoute) setConversationRoute(conversation.id);

    this.conversation = conversation;
    this.messages = [];
    this.attachments = [];
    this.#seen = new Set();
    this.humans.clear();
    this.attention.clear();

    wire.connect(conversation.id, this.identity, (event, context) => this.#onWireEvent(event, context));

    let detail;
    try {
      detail = await api.conversation(conversation.id);
    } catch {
      // The line went away between being listed and being opened.
      if (epoch === this.#epoch) this.leave();
      return;
    }
    if (epoch !== this.#epoch) return; // a newer line won the race

    this.conversation = detail.conversation;
    this.attachments = detail.attachments;
    for (const message of detail.messages) this.#absorb(message);
    this.loadConversations().catch(() => {});
  }

  /** Step off the current line without choosing another. */
  leave({ clearRoute = true } = {}) {
    this.#epoch++;
    wire.disconnect();
    this.conversation = null;
    this.messages = [];
    this.attachments = [];
    this.#seen = new Set();
    this.humans.clear();
    this.attention.clear();
    if (clearRoute && routedConversationId()) clearConversationRoute();
  }

  /** The URL changed under us — Back, Forward, or a pasted link. */
  onRouteChange() {
    const id = routedConversationId();
    const target = id && this.conversations.find((c) => c.id === id);
    if (target) {
      if (this.conversation?.id !== target.id) this.open(target, { fromRoute: true });
    } else if (this.conversation) {
      this.leave({ clearRoute: false });
    }
  }

  // ── talking ────────────────────────────────────────────────────────────
  say(body) {
    const text = body.trim();
    if (!text) return false;
    return wire.send({ sender: session.handle, body: text });
  }

  /** Post to a line we are not on — see `sendOffLine`. */
  warn(convId, body) {
    return sendOffLine(convId, this.identity, body);
  }

  showNotice(message, kind = "") {
    this.notice = { message, kind };
    clearTimeout(this.#noticeTimer);
    this.#noticeTimer = setTimeout(() => { this.notice = null; }, 4200);
  }

  // ── server events ──────────────────────────────────────────────────────
  #onWireEvent(event, context) {
    const convId = this.conversation?.id;

    switch (event.type) {
      case "message":
        this.#absorb(event.message);
        break;

      case "attachment":
        this.upsertAttachment(event.attachment);
        break;

      case "attention":
        this.attention.add(event.attachment_id);
        break;

      case "conversation":
        if (event.conversation.id === convId) {
          this.conversation = event.conversation;
          this.loadConversations().catch(() => {});
        }
        break;

      case "conversation_archived":
      case "conversation_deleted":
        if (event.conversation_id === convId) this.leave();
        this.loadConversations().catch(() => {});
        this.refreshArchiveIfOpen();
        break;

      case "error":
        if (event.conversation_id === convId) this.#onWireError(event, context);
        break;
    }
  }

  /**
   * A refusal means one of two quite different things, and the page used to
   * show the same thing for both.
   *
   * Before the handshake ever succeeded, the *handle* was refused — someone
   * else holds it on this line — so the gate reopens saying why. After a
   * successful handshake, the handle was fine and the *line* has gone; that is
   * a toast, not a sign-in problem.
   */
  #onWireError(event, context) {
    const message = event.message || "this line is no longer available";

    if (message.includes("archived")) {
      this.showNotice(message, "error");
      this.leave();
      this.loadConversations().catch(() => {});
      this.refreshArchiveIfOpen();
      return;
    }
    if (!context.wasReady && !context.claimRejected) {
      context.rejectClaim();
      session.openGate(message);
      return;
    }
    this.showNotice(message, "error");
  }

  /**
   * Record an attachment, whether it arrived over the socket or as the answer
   * to our own POST.
   *
   * Keyed by id and therefore idempotent, which is what lets both paths call
   * it. Both need to: the socket is the normal route, but if it happens to be
   * reconnecting when the attach succeeds, the REST response is the only news
   * we get — and a process running with no jack on the board is worse than a
   * jack that arrives twice.
   */
  upsertAttachment(attachment) {
    const index = this.attachments.findIndex((a) => a.id === attachment.id);
    if (index >= 0) this.attachments[index] = attachment;
    else this.attachments.push(attachment);
    // A process that has exited is no longer waiting on you.
    if (!isLive(attachment)) this.attention.delete(attachment.id);
  }

  /** Add a message once, remembering who spoke so the autocomplete knows them. */
  #absorb(message) {
    if (this.#seen.has(message.id)) return;
    this.#seen.add(message.id);
    if (message.sender_type === "human" && message.sender.toLowerCase() !== (session.handle || "").toLowerCase()) {
      this.humans.add(message.sender);
    }
    this.messages.push(message);
  }
}

export const room = new Room();
