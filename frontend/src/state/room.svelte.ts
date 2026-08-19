/**
 * The room: the list of lines, the line you are on, and everything on it.
 *
 * This turns server events into screen state and owns two ordering guards:
 *   - **`#epoch`** rises on line changes, discarding late awaits so a slower
 *     fetch cannot overwrite the line chosen after it.
 *   - **`#seen`** holds message ids, because a reconnect replays history and
 *     the same message will arrive twice.
 */

import { SvelteSet } from "svelte/reactivity";
import { api } from "../lib/api";
import type {
  Attachment,
  ChatMessage,
  Conversation,
  ErrorEvent,
  ReattachAction,
  ReattachOfferEvent,
  WireEvent,
} from "../lib/contracts";
import { session } from "./session.svelte.js";
import { wire, sendOffLine } from "./wire.svelte.js";
import type { WireContext, WireIdentity } from "./wire.svelte.js";
import { clearConversationRoute, routedConversationId, setConversationRoute } from "../lib/routing";
import { isLive } from "../lib/attachments";
import { presenceSync } from "./presence-coordinator.svelte.js";

export interface RoomNotice {
  message: string;
  kind: "" | "error";
}

interface OpenOptions {
  fromRoute?: boolean;
}

interface LeaveOptions {
  clearRoute?: boolean;
}

function ignoreBackgroundFailure(): void {
  // Best-effort refreshes already have a primary UI state to preserve.
}

class Room {
  conversations = $state<Conversation[]>([]);
  archived = $state<Conversation[]>([]);
  archiveOpen = $state(false);

  conversation = $state<Conversation | null>(null);
  messages = $state<ChatMessage[]>([]);
  attachments = $state<Attachment[]>([]);
  /** A persisted restart offer is visible only on the line that created it. */
  reattachOffer = $state<ReattachOfferEvent | null>(null);

  /** Speakers for @ autocomplete. `SvelteSet` makes `.add()` reactive. */
  humans = new SvelteSet<string>();
  /** Attachments blocked on a dialog, which the board rings until someone peeks. */
  attention = new SvelteSet<string>();

  /** A transient toast, distinct from the wire banner: this one goes away. */
  notice = $state<RoomNotice | null>(null);

  #seen = new Set<number>();
  #epoch = 0;
  #noticeTimer: ReturnType<typeof setTimeout> | null = null;

  get identity(): WireIdentity {
    if (!session.handle) throw new Error("a handle is required before joining a line");
    return { handle: session.handle, clientId: session.clientId };
  }

  // ── the list ───────────────────────────────────────────────────────────
  async loadConversations(): Promise<void> {
    this.conversations = await api.conversations();
    // Arriving on a deep link: the route named a line before the list existed.
    const routedId = routedConversationId();
    if (!routedId) return;
    const routed = this.conversations.find((conversation) => conversation.id === routedId);
    if (routed && this.conversation?.id !== routed.id) void this.open(routed, { fromRoute: true });
  }

  async loadArchived(): Promise<void> {
    this.archived = await api.conversations(true);
  }

  refreshArchiveIfOpen(): void {
    if (this.archiveOpen) void this.loadArchived().catch(ignoreBackgroundFailure);
  }

  async createConversation(name: string): Promise<void> {
    const created = await api.createConversation(name);
    await this.loadConversations();
    void this.open(created);
  }

  // ── the line you are on ────────────────────────────────────────────────
  async open(conversation: Conversation, { fromRoute = false }: OpenOptions = {}): Promise<void> {
    const epoch = ++this.#epoch;
    const presenceFetch = presenceSync.open();
    if (!fromRoute) setConversationRoute(conversation.id);

    this.conversation = conversation;
    this.messages = [];
    this.attachments = [];
    this.#seen = new Set<number>();
    this.humans.clear();
    this.attention.clear();
    this.reattachOffer = null;

    wire.connect(
      conversation.id,
      this.identity,
      (event, context) => {
        this.#onWireEvent(event, context);
      },
      () => {
        void this.resync().catch(ignoreBackgroundFailure);
      },
      (hello) => {
        session.acceptHandshake(hello.version, hello.instance_name);
      },
    );

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
    presenceSync.finish(presenceFetch, detail.presence, detail.working);
    for (const message of detail.messages) this.#absorb(message);
    void this.loadConversations().catch(ignoreBackgroundFailure);
  }

  /**
   * Catch up with the server after the wire came back.
   *
   * Events are only delivered to a connected socket, so an outage is a hole in
   * this tab's knowledge that nothing else fills — `open()` is the only other
   * thing that fetches, and it runs on line changes, not on recovery. A server
   * restart lands squarely in that hole: it rewrites every attachment status
   * with no sockets to tell. The symptom was a process shown as dead while it
   * was running, cleared only by a manual refresh.
   *
   * Attachments are replaced outright because the server is authoritative about
   * them. Messages are merged, since `#absorb` already dedupes by id and the
   * feed must not lose anything said while we were away.
   */
  async resync(): Promise<void> {
    const conversation = this.conversation;
    if (!conversation) return;
    const epoch = this.#epoch;
    const [detail, presenceFetch] = await presenceSync.fetch(api.conversation(conversation.id));
    if (epoch !== this.#epoch) return; // the line changed under the fetch

    this.conversation = detail.conversation;
    this.attachments = detail.attachments;
    presenceSync.finish(presenceFetch, detail.presence, detail.working);
    for (const message of detail.messages) this.#absorb(message);
  }

  /** Step off the current line without choosing another. */
  leave({ clearRoute = true }: LeaveOptions = {}): void {
    this.#epoch++;
    presenceSync.reset();
    wire.disconnect();
    this.conversation = null;
    this.messages = [];
    this.attachments = [];
    this.#seen = new Set<number>();
    this.humans.clear();
    this.attention.clear();
    this.reattachOffer = null;
    if (clearRoute && routedConversationId()) clearConversationRoute();
  }

  /** The URL changed under us — Back, Forward, or a pasted link. */
  onRouteChange(): void {
    const id = routedConversationId();
    const target = id && this.conversations.find((c) => c.id === id);
    if (target) {
      if (this.conversation?.id !== target.id) void this.open(target, { fromRoute: true });
    } else if (this.conversation) {
      this.leave({ clearRoute: false });
    }
  }

  // ── talking ────────────────────────────────────────────────────────────
  say(body: string): boolean {
    const text = body.trim();
    if (!text) return false;
    return wire.send({ sender: this.identity.handle, body: text });
  }
  /** Post to a line we are not on — see `sendOffLine`. */
  warn(convId: string, body: string): Promise<void> {
    return sendOffLine(convId, this.identity, body);
  }

  showNotice(message: string, kind: RoomNotice["kind"] = ""): void {
    this.notice = { message, kind };
    if (this.#noticeTimer !== null) clearTimeout(this.#noticeTimer);
    this.#noticeTimer = setTimeout(() => {
      this.notice = null;
    }, 4200);
  }
  // ── server events ──────────────────────────────────────────────────────
  #onWireEvent(event: WireEvent, context: WireContext): void {
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

      case "working":
        presenceSync.apply(event);
        break;

      case "reattach_offer":
        if (event.conversation_id === convId) this.reattachOffer = event;
        break;

      case "reattach_decision":
        if (event.conversation_id === convId && event.token === this.reattachOffer?.token) {
          this.reattachOffer = null;
        }
        break;

      case "conversation":
        if (event.conversation.id === convId) {
          this.conversation = event.conversation;
          void this.loadConversations().catch(ignoreBackgroundFailure);
        }
        break;

      case "conversation_archived":
      case "conversation_deleted":
        if (event.conversation_id === convId) this.leave();
        void this.loadConversations().catch(ignoreBackgroundFailure);
        this.refreshArchiveIfOpen();
        break;

      case "error":
        if (event.conversation_id === convId) this.#onWireError(event, context);
        break;
    }
  }

  chooseReattach(action: ReattachAction): boolean {
    const offer = this.reattachOffer;
    return offer ? wire.chooseReattach(offer.token, action) : false;
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
  #onWireError(event: ErrorEvent, context: WireContext): void {
    const message = event.message || "this line is no longer available";

    if (message.includes("archived")) {
      this.showNotice(message, "error");
      this.leave();
      void this.loadConversations().catch(ignoreBackgroundFailure);
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
  upsertAttachment(attachment: Attachment): void {
    const index = this.attachments.findIndex((candidate) => candidate.id === attachment.id);
    if (index >= 0) this.attachments[index] = attachment;
    else this.attachments.push(attachment);
    // A process that has exited is no longer waiting on you.
    if (!isLive(attachment)) this.attention.delete(attachment.id);
  }

  /** Add a message once and remember its human sender for autocomplete. */
  #absorb(message: ChatMessage): void {
    if (this.#seen.has(message.id)) return;
    this.#seen.add(message.id);
    if (
      message.sender_type === "human" &&
      message.sender.toLowerCase() !== (session.handle?.toLowerCase() ?? "")
    ) {
      this.humans.add(message.sender);
    }
    this.messages.push(message);
  }
}

export const room = new Room();
