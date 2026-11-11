/** Wire events that mutate the open line — kept out of room.svelte.ts for the line cap. */
import type { Attachment, ChatMessage, Conversation, LineLiveEvent, WireEvent } from "../lib/contracts";
import { handleWireError, type RefusalTarget } from "./room-wire-error";
import type { WireContext } from "./wire.svelte.js";
import { presenceSync } from "./presence-coordinator.svelte.js";
import { applyPendingWireEvent, ignoreBackgroundFailure } from "./room-pending-sync.js";
import type { Pin } from "../lib/pin-contracts";
import { resources } from "./resources.svelte.js";
import { screenStatus } from "./screen-status.svelte.js";
import { voicePresets } from "./voice-presets.svelte.js";

export interface RoomWireSink extends RefusalTarget {
  conversation: Conversation | null;
  conversations: Conversation[];
  reattachOffer: { token: string } | null;
  screenShare: import("../lib/screen-api").ScreenShare | null;
  attachments: Attachment[];
  attention: { add(id: string): void; delete(id: string): void };
  archiveOpen: boolean;
  absorb(message: ChatMessage): void;
  upsertAttachment(attachment: Attachment): void;
  removeAttachment(attachmentId: string): void;
  setCaptain(conversationId: string, attachmentId: string | null): void;
  setLineLive(event: LineLiveEvent): void;
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
    case "screen_snapshot":
      screenStatus.indicators = event.indicators;
      screenStatus.devices = event.devices;
      room.screenShare = event.share;
      break;
    case "screen_share":
      screenStatus.revision++;
      room.screenShare = event.share;
      break;
    case "screen_devices_changed":
      screenStatus.revision++;
      break;
    case "reaction":
      room.history.updateReactions(event.message_id, event.reactions);
      break;
    case "pins_changed":
      if (event.conversation_id === convId) room.pins.replace(event.pins);
      break;
    case "attachment":
      room.upsertAttachment(event.attachment);
      break;
    case "captain_changed":
      room.setCaptain(event.conversation_id, event.attachment_id);
      break;
    case "attachment_removed":
      room.removeAttachment(event.attachment_id);
      break;
    case "memory_usage": {
      const attachment = room.attachments.find((item) => item.id === event.attachment_id);
      if (attachment) {
        room.upsertAttachment({
          ...attachment,
          memory_usage_bytes: event.usage_bytes,
          memory_raw_bytes: event.raw_bytes ?? null,
          memory_anon_bytes: event.anon_bytes ?? null,
          memory_file_bytes: event.file_bytes ?? null,
          memory_kernel_bytes: event.kernel_bytes ?? null,
          memory_cap_bytes: event.cap_bytes,
          memory_percent: event.percent,
        });
      }
      break;
    }
    case "resources":
      resources.snapshot = event.snapshot;
      break;
    case "line_live":
      room.setLineLive(event);
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
    case "approvals_changed":
    case "restart_request":
    case "write_set_grant_request":
    case "memory_request":
      applyPendingWireEvent(event);
      break;
    case "asr_presets_changed":
      voicePresets.receive(event.settings);
      break;
    case "error":
      if (event.conversation_id === convId) handleWireError(room, event, context);
      break;
  }
}
