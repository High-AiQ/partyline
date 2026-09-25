/** The room: lines, the active line, and everything on it.
 *  `#epoch` rises on line changes so late fetches cannot overwrite the chosen line. */

import { SvelteSet } from "svelte/reactivity";
import { api } from "../lib/api";
import { toggleReaction } from "../lib/reaction-api";
import type {
  Attachment,
  ChatMessage,
  Conversation,
  ReattachAction,
  ReattachOfferEvent,
  WireEvent,
} from "../lib/contracts";
import { session } from "./session.svelte.js";
import { sayOnLine } from "../lib/room-say";
import { sendOffLine } from "../lib/offline-wire";
import type { WireIdentity } from "../lib/wire-commands";
import { restart } from "./restart.svelte.js";
import { leavePendingBanners, openPendingBanners, resyncPendingBanners } from "./room-pending-sync.js";
import { onRoomWireEvent } from "./room-wire-events.js";
import { wire } from "./wire.svelte.js";
import type { WireContext } from "./wire.svelte.js";
import { clearConversationRoute, routedConversationId, setConversationRoute } from "../lib/routing";
import { isLive, withoutForgotten } from "../lib/attachments";
import { MessageHistory } from "./message-history.svelte";
import { presenceSync } from "./presence-coordinator.svelte.js";
import { draft } from "./draft.svelte.js";

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
  attachments = $state<Attachment[]>([]);
  captains = $state<Record<string, string | null>>({});
  reattachOffer = $state<ReattachOfferEvent | null>(null);
  history = new MessageHistory(() => session.handle);
  attention = new SvelteSet<string>();
  #removed = new Set<string>();

  notice = $state<RoomNotice | null>(null);

  #epoch = 0;
  #noticeTimer: ReturnType<typeof setTimeout> | null = null;

  get identity(): WireIdentity {
    if (!session.handle) throw new Error("authentication is required before joining a line");
    return { clientId: session.clientId };
  }

  get messages(): ChatMessage[] {
    return this.history.messages;
  }

  set messages(messages: ChatMessage[]) {
    this.history.replace(messages);
  }

  // ── the list ───────────────────────────────────────────────────────────
  async loadConversations(): Promise<void> {
    this.conversations = await api.conversations();
    void restart.load().catch(ignoreBackgroundFailure);
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
    draft.openLine(conversation.id);
    this.history.reset();
    this.attachments = [];
    this.attention.clear();
    this.#removed.clear();
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
        session.acceptHandshake(hello.version, hello.instance_name, hello.handle);
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
    if (epoch !== this.#epoch) return;

    this.conversation = detail.conversation;
    this.attachments = withoutForgotten(detail.attachments, this.#removed);
    presenceSync.finish(presenceFetch, detail.presence, detail.working);
    this.history.seed(detail.messages, detail.has_more_messages);
    openPendingBanners(conversation.id);
    void this.loadConversations().catch(ignoreBackgroundFailure);
  }

  async resync(): Promise<void> {
    const conversation = this.conversation;
    if (!conversation) return;
    const epoch = this.#epoch;
    const afterId = this.history.newestId;
    const [detail, presenceFetch] = await presenceSync.fetch(api.conversation(conversation.id));
    if (epoch !== this.#epoch) return;

    this.conversation = detail.conversation;
    this.attachments = withoutForgotten(detail.attachments, this.#removed);
    presenceSync.finish(presenceFetch, detail.presence, detail.working);
    this.history.merge(detail.messages);
    await this.history.catchUp(conversation.id, afterId);
    resyncPendingBanners(conversation.id);
  }

  async toggleReaction(messageId: number, emoji: string): Promise<void> {
    try {
      const message = await toggleReaction(messageId, emoji);
      this.history.updateReactions(message.id, message.reactions ?? []);
    } catch (failure: unknown) {
      this.showNotice(failure instanceof Error ? failure.message : "could not toggle reaction", "error");
    }
  }

  loadOlderMessages(): Promise<number> {
    const conversation = this.conversation;
    return conversation ? this.history.loadOlder(conversation.id) : Promise.resolve(0);
  }

  /** Step off the current line without choosing another. */
  leave({ clearRoute = true }: LeaveOptions = {}): void {
    this.#epoch++;
    presenceSync.reset();
    wire.disconnect();
    this.conversation = null;
    draft.leaveLine();
    this.history.reset();
    this.attachments = [];
    this.attention.clear();
    this.#removed.clear();
    this.reattachOffer = null;
    leavePendingBanners();
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
  // ── talking ─────────────────────────────────────────────────────────
  async say(body: string): Promise<boolean> {
    const conversation = this.conversation;
    if (!conversation) return false;
    const result = await sayOnLine(conversation.id, body);
    if (!result.ok) {
      if (result.error) this.showNotice(result.error, "error");
      return false;
    }
    if (result.message) this.#absorb(result.message);
    return true;
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
    onRoomWireEvent(this, event, context);
  }

  chooseReattach(action: ReattachAction): boolean {
    const offer = this.reattachOffer;
    return offer ? wire.chooseReattach(offer.token, action) : false;
  }

  /**
   * Record an attachment from the socket or from our own POST's answer. Keyed
   * by id, so idempotent: if the socket is reconnecting when the attach lands,
   * the REST response is the only news, and a running process with no jack is
   * worse than a jack that arrives twice.
   */
  upsertAttachment(attachment: Attachment): void {
    if (this.#removed.has(attachment.id)) return; // a late echo of a forgotten jack
    const index = this.attachments.findIndex((candidate) => candidate.id === attachment.id);
    if (index >= 0) this.attachments[index] = attachment;
    else this.attachments.push(attachment);
    // A process that has exited is no longer waiting on you.
    if (!isLive(attachment)) this.attention.delete(attachment.id);
  }

  /** Forget a jack; idempotent for the same reason `upsertAttachment` is. */
  removeAttachment(attachmentId: string): void {
    this.#removed.add(attachmentId);
    this.attachments = this.attachments.filter((candidate) => candidate.id !== attachmentId);
    this.attention.delete(attachmentId);
  }

  setCaptain(conversationId: string, attachmentId: string | null): void {
    this.captains[conversationId] = attachmentId;
  }
  #absorb(message: ChatMessage): void {
    this.history.merge([message]);
  }

  absorb(message: ChatMessage): void {
    this.#absorb(message);
  }
}

export const room = new Room();
