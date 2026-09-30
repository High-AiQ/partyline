/** Bounded human history with stable ids across pages, wire events, and reconnects. */

import { SvelteMap, SvelteSet } from "svelte/reactivity";
import { api } from "../lib/api";
import { messagesAround } from "../lib/message-api";
import type { ChatMessage, ReactionResponse } from "../lib/contracts";

const PAGE_SIZE = 20;
const GAP_PAGES_PER_LOAD = 2;

export interface HistoryGap {
  afterId: number;
  beforeId: number | null;
}

export class MessageHistory {
  messages = $state<ChatMessage[]>([]);
  hasOlder = $state(false);
  loadingOlder = $state(false);
  olderError = $state(false);
  hasNewer = $state(false);
  gaps = $state<HistoryGap[]>([]);
  loadingGapAfterId = $state<number | null>(null);
  highlightedId = $state<number | null>(null);
  jumpedAway = $state(false);
  scrollRequest = $state(0);
  scrollToLive = $state(false);
  humans = new SvelteSet<string>();

  #seen = new SvelteSet<number>();
  #generation = 0;
  #highlightTimer: ReturnType<typeof setTimeout> | undefined;
  #currentHandle: () => string | null;

  constructor(currentHandle: () => string | null) {
    this.#currentHandle = currentHandle;
  }

  get oldestId(): number | null {
    return this.messages.at(0)?.id ?? null;
  }

  get newestId(): number {
    return this.messages.at(-1)?.id ?? 0;
  }

  reset(): void {
    this.#generation++;
    this.messages = [];
    this.hasOlder = false;
    this.loadingOlder = false;
    this.olderError = false;
    this.hasNewer = false;
    this.gaps = [];
    this.loadingGapAfterId = null;
    this.highlightedId = null;
    this.jumpedAway = false;
    this.scrollToLive = false;
    clearTimeout(this.#highlightTimer);
    this.#seen = new SvelteSet<number>();
    this.humans.clear();
  }

  replace(messages: ChatMessage[]): void {
    this.reset();
    this.merge(messages);
  }

  seed(messages: ChatMessage[], hasOlder: boolean): void {
    this.merge(messages);
    this.hasOlder = hasOlder;
  }

  merge(messages: ChatMessage[]): number {
    const fresh = messages.filter((message) => !this.#seen.has(message.id));
    if (!fresh.length) return 0;
    for (const message of fresh) {
      this.#seen.add(message.id);
      if (
        message.sender_type === "human" &&
        message.sender.toLowerCase() !== (this.#currentHandle()?.toLowerCase() ?? "")
      ) {
        this.humans.add(message.sender);
      }
    }
    this.messages = [...this.messages, ...fresh].sort((left, right) => left.id - right.id);
    return fresh.length;
  }

  updateReactions(messageId: number, reactions: ReactionResponse[]): void {
    const index = this.messages.findIndex((message) => message.id === messageId);
    if (index < 0) return;
    const message = this.messages[index];
    if (!message) return;
    this.messages[index] = { ...message, reactions };
    this.messages = [...this.messages];
  }

  async loadOlder(conversationId: string): Promise<number> {
    const beforeId = this.oldestId;
    if (beforeId === null || !this.hasOlder || this.loadingOlder) return 0;
    const generation = this.#generation;
    this.loadingOlder = true;
    this.olderError = false;
    try {
      const page = await api.messagePage(conversationId, { beforeId, limit: PAGE_SIZE });
      if (generation !== this.#generation) return 0;
      this.hasOlder = page.has_more;
      return this.merge(page.messages);
    } catch (failure: unknown) {
      if (generation === this.#generation) this.olderError = true;
      throw failure;
    } finally {
      if (generation === this.#generation) this.loadingOlder = false;
    }
  }

  async catchUp(conversationId: string, afterId: number): Promise<void> {
    const generation = this.#generation;
    let cursor = afterId;
    for (;;) {
      const page = await api.messagePage(conversationId, { afterId: cursor, limit: PAGE_SIZE });
      if (generation !== this.#generation) return;
      this.merge(page.messages);
      const next = page.messages.at(-1)?.id;
      if (!page.has_more || next === undefined) return;
      cursor = next;
    }
  }

  async jumpAround(conversationId: string, messageId: number): Promise<void> {
    const generation = this.#generation;
    if (!this.#seen.has(messageId)) {
      const window = await messagesAround(conversationId, messageId, 10);
      if (generation !== this.#generation) return;
      const firstId = window.messages.at(0)?.id;
      const lastId = window.messages.at(-1)?.id;
      if (firstId !== undefined && lastId !== undefined) {
        if (this.oldestId === null || firstId <= this.oldestId) {
          this.hasOlder = window.has_more_before;
        }
        this.#recordGaps(firstId, lastId, window.has_more_before, window.has_more_after);
      }
      this.merge(window.messages);
    }
    this.hasNewer = this.gaps.length > 0;
    this.highlightedId = messageId;
    this.jumpedAway = true;
    this.scrollToLive = false;
    this.scrollRequest++;
    clearTimeout(this.#highlightTimer);
    this.#highlightTimer = setTimeout(() => {
      if (this.highlightedId === messageId) this.highlightedId = null;
    }, 2400);
  }

  async loadNewer(conversationId: string, afterId = this.gaps[0]?.afterId): Promise<number> {
    const gap = this.gaps.find((candidate) => candidate.afterId === afterId);
    if (!gap || this.loadingGapAfterId !== null) return 0;
    const generation = this.#generation;
    let cursor = gap.afterId;
    let added = 0;
    this.loadingGapAfterId = gap.afterId;
    try {
      let currentAfterId = gap.afterId;
      for (let loadedPages = 0; loadedPages < GAP_PAGES_PER_LOAD; loadedPages++) {
        const page = await api.messagePage(conversationId, { afterId: cursor, limit: PAGE_SIZE });
        if (generation !== this.#generation) return 0;
        const next = page.messages.at(-1)?.id;
        if (next === undefined || next <= cursor) {
          this.#removeGap(currentAfterId);
          return added;
        }
        added += this.merge(page.messages);
        if (!page.has_more || (gap.beforeId !== null && next >= gap.beforeId)) {
          this.#removeGap(currentAfterId);
          return added;
        }
        cursor = next;
        this.#moveGap(currentAfterId, cursor, gap.beforeId);
        currentAfterId = cursor;
      }
      return added;
    } finally {
      if (generation === this.#generation) this.loadingGapAfterId = null;
    }
  }

  async returnToLive(conversationId: string): Promise<void> {
    const generation = ++this.#generation;
    this.loadingOlder = false;
    this.loadingGapAfterId = null;
    const page = await api.messagePage(conversationId, { limit: PAGE_SIZE });
    if (generation !== this.#generation) return;
    const newestTailId = page.messages.at(-1)?.id ?? 0;
    const newer = this.messages.filter((message) => message.id > newestTailId);
    this.messages = [];
    this.#seen = new SvelteSet<number>();
    this.gaps = [];
    this.hasNewer = false;
    this.loadingGapAfterId = null;
    this.loadingOlder = false;
    this.olderError = false;
    this.hasOlder = page.has_more;
    this.merge([...page.messages, ...newer]);
    this.hasNewer = false;
    this.jumpedAway = false;
    this.highlightedId = null;
    this.scrollToLive = true;
    this.scrollRequest++;
    clearTimeout(this.#highlightTimer);
  }

  #recordGaps(firstId: number, lastId: number, hasBefore: boolean, hasAfter: boolean): void {
    const overlapping = this.gaps.filter(
      (gap) => gap.afterId < lastId && (gap.beforeId === null || gap.beforeId > firstId),
    );
    const retained = this.gaps.filter((gap) => !overlapping.includes(gap));
    for (const gap of overlapping) {
      if (hasBefore && firstId > gap.afterId) {
        retained.push({ afterId: gap.afterId, beforeId: firstId });
      }
      if (hasAfter && (gap.beforeId === null || lastId < gap.beforeId)) {
        retained.push({ afterId: lastId, beforeId: gap.beforeId });
      }
    }
    const nextLoadedId = this.messages.find((message) => message.id > lastId)?.id ?? null;
    if (hasAfter && !overlapping.length && !this.#seen.has(lastId)) {
      retained.push({ afterId: lastId, beforeId: nextLoadedId });
    }
    const unique = new SvelteMap<string, HistoryGap>();
    for (const gap of retained) {
      const key = `${String(gap.afterId)}:${gap.beforeId === null ? "end" : String(gap.beforeId)}`;
      unique.set(key, gap);
    }
    this.gaps = [...unique.values()].sort((left, right) => left.afterId - right.afterId);
    this.hasNewer = this.gaps.length > 0;
  }

  #removeGap(afterId: number): void {
    this.gaps = this.gaps.filter((gap) => gap.afterId !== afterId);
    this.hasNewer = this.gaps.length > 0;
  }

  #moveGap(afterId: number, nextAfterId: number, beforeId: number | null): void {
    this.gaps = this.gaps.filter((gap) => gap.afterId !== afterId).concat({ afterId: nextAfterId, beforeId });
    this.hasNewer = this.gaps.length > 0;
  }
}
