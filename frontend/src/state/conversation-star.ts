import { setConversationStar } from "../lib/conversation-star-api";
import type { Conversation } from "../lib/contracts";

interface StarRoom {
  conversations: Conversation[];
  loadConversations(): Promise<void>;
  showNotice(message: string, kind: "error"): void;
}

export async function toggleConversationStar(room: StarRoom, id: string): Promise<void> {
  const line = room.conversations.find((candidate) => candidate.id === id);
  if (!line) return;
  try {
    await setConversationStar(id, !line.starred);
    await room.loadConversations();
  } catch (failure: unknown) {
    room.showNotice(failure instanceof Error ? failure.message : "could not star line", "error");
  }
}
