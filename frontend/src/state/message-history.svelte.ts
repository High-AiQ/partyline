/** Bounded human history with stable ids across pages, wire events, and reconnects. */

import { SvelteSet } from "svelte/reactivity";
import { api } from "../lib/api";
import type { ChatMessage } from "../lib/contracts";

const PAGE_SIZE = 20;

export class MessageHistory {
  messages = $state<ChatMessage[]>([]);
  hasOlder = $state(false);
  loadingOlder = $state(false);
  olderError = $state(false);
  humans = new SvelteSet<string>();

  #seen = new SvelteSet<number>();
  #generation = 0;
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
}
