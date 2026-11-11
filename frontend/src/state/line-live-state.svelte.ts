/** Per-line live roster revisions for dialogs that can outlast line updates. */

import type { Conversation, LineLiveEvent } from "../lib/contracts";
import { applyLineLive } from "../lib/line-live";

class LineLiveState {
  revisions = $state<Record<string, number>>({});

  reconcile(previous: Conversation[], updated: Conversation[]): void {
    const before = new Map(previous.map((line) => [line.id, line]));
    const after = new Map(updated.map((line) => [line.id, line]));
    for (const id of new Set([...before.keys(), ...after.keys()])) {
      const oldLine = before.get(id);
      const newLine = after.get(id);
      if (
        oldLine?.live_count !== newLine?.live_count ||
        oldLine?.archived_at !== newLine?.archived_at ||
        oldLine?.parent_id !== newLine?.parent_id
      ) {
        this.#bump(id);
      }
    }
  }

  apply(conversations: Conversation[], event: LineLiveEvent): Conversation[] {
    const current = conversations.find((line) => line.id === event.conversation_id);
    if (!current || current.live_count === event.live_count) return conversations;
    this.#bump(event.conversation_id);
    return applyLineLive(conversations, event);
  }

  #bump(conversationId: string): void {
    this.revisions[conversationId] = (this.revisions[conversationId] ?? 0) + 1;
  }
}

export const lineLiveState = new LineLiveState();
