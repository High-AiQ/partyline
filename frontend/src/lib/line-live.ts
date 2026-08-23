/** Apply one global line-presence event without refetching the rail. */

import type { Conversation, LineLiveEvent } from "./contracts";

export function applyLineLive(conversations: Conversation[], event: LineLiveEvent): Conversation[] {
  return conversations.map((conversation) =>
    conversation.id === event.conversation_id
      ? { ...conversation, live_count: event.live_count }
      : conversation,
  );
}
