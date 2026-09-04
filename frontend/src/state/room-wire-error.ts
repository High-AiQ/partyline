/**
 * What the room does with a wire refusal, split from the at-cap room store.
 *
 * A refusal means one of two quite different things, and the page used to
 * show the same thing for both.
 *
 * A pre-handshake refusal is terminal for this connection; retrying the same
 * rejected line forever would hide the server's useful error behind a banner.
 */

import type { ErrorEvent } from "../lib/contracts";
import type { WireContext } from "./wire.svelte.js";

/** The slice of the room a refusal is allowed to touch. */
export interface RefusalTarget {
  showNotice(message: string, kind: "" | "error"): void;
  leave(): void;
  loadConversations(): Promise<void>;
  refreshArchiveIfOpen(): void;
}

function ignoreBackgroundFailure(): void {
  // Best-effort refreshes already have a primary UI state to preserve.
}

export function handleWireError(room: RefusalTarget, event: ErrorEvent, context: WireContext): void {
  const message = event.message || "this line is no longer available";

  if (message.includes("archived")) {
    room.showNotice(message, "error");
    room.leave();
    void room.loadConversations().catch(ignoreBackgroundFailure);
    room.refreshArchiveIfOpen();
    return;
  }
  if (!context.wasReady && !context.claimRejected) {
    context.rejectClaim();
    room.showNotice(message, "error");
    return;
  }
  room.showNotice(message, "error");
}
