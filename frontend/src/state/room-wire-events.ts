/** Wire events that mutate the open line — kept out of room.svelte.ts for the line cap. */
import type { Attachment, ChatMessage, Conversation, WireEvent } from "../lib/contracts";
import { applyLineLive } from "../lib/line-live";
import { handleWireError, type RefusalTarget } from "./room-wire-error";
import type { WireContext } from "./wire.svelte.js";
import { presenceSync } from "./presence-coordinator.svelte.js";
import { applyPendingWireEvent, ignoreBackgroundFailure } from "./room-pending-sync.js";
import type { Pin } from "../lib/pin-contracts";
import { resources } from "./resources.svelte.js";

export interface RoomWireSink extends RefusalTarget {
  conversation: Conversation | null;
  conversations: Conversation[];
  reattachOffer: { token: string } | null;
  attachments: Attachment[];
  attention: { add(id: string): void; delete(id: string): void };
  archiveOpen: boolean;
  absorb(message: ChatMessage): void;
  upsertAttachment(attachment: Attachment): void;
  removeAttachment(attachmentId: string): void;
  leave(): void;
  loadConversations(): Promise<void>;
  refreshArchiveIfOpen(): void;
  history: { updateReactions(messageId: number, reactions: unknown[]): void };
  pins: { replace(pins: Pin[]): void };
}

export function onRoomWireEvent(room: RoomWireSink, event: WireEvent, context: WireContext): void {
  const convId = room.conversation?.id;
  switch (event.type) {
    case "message":
      room.absorb(event.message);
      break;
    case "reaction":
      room.history.updateReactions(event.message_id, event.reactions);
      break;
    case "pins_changed":
      if (event.conversation_id === convId) room.pins.replace(event.pins);
      break;
    case "attachment":
      resources.scheduleRefresh();
      room.upsertAttachment(event.attachment);
      break;
    case "attachment_removed":
      resources.scheduleRefresh();
      room.removeAttachment(event.attachment_id);
      break;
    case "memory_usage": {
      const attachment = room.attachments.find((item) => item.id === event.attachment_id);
      if (attachment) {
        room.upsertAttachment({
          ...attachment,
          memory_usage_bytes: event.usage_bytes,
          memory_cap_bytes: event.cap_bytes,
          memory_percent: event.percent,
        });
      }
      break;
    }
    case "line_live":
      resources.scheduleRefresh();
      room.conversations = applyLineLive(room.conversations, event);
      break;
    case "attention":
      room.attention.add(event.attachment_id);
      break;
    case "working":
      presenceSync.apply(event);
      break;
    case "reattach_offer":
      if (event.conversation_id === convId) room.reattachOffer = event;
      break;
    case "reattach_decision":
      if (event.conversation_id === convId && event.token === room.reattachOffer?.token) {
        room.reattachOffer = null;
      }
      break;
    case "conversation":
      if (event.conversation.id === convId) {
        room.conversation = event.conversation;
        void room.loadConversations().catch(ignoreBackgroundFailure);
      }
      break;
    case "conversation_archived":
    case "conversation_deleted":
      if (event.conversation_id === convId) room.leave();
      void room.loadConversations().catch(ignoreBackgroundFailure);
      room.refreshArchiveIfOpen();
      break;
    case "conversations_changed":
      void room.loadConversations().catch(ignoreBackgroundFailure);
      room.refreshArchiveIfOpen();
      break;
    case "restart_request":
    case "write_set_grant_request":
    case "memory_request":
      applyPendingWireEvent(event);
      break;
    case "error":
      if (event.conversation_id === convId) handleWireError(room, event, context);
      break;
  }
}
