/** Apply lifecycle responses even when the socket is reconnecting. */
import { ApiError, api } from "../lib/api";
import { room } from "./room.svelte.js";

/** Resume and restart share one route: the server reruns a non-listener fresh.
 *  Returns the failure message (also toasted) so the card can keep it in view. */
export async function activateJack(attachmentId: string, restart: boolean): Promise<string | null> {
  try {
    room.upsertAttachment(await api.resume(attachmentId));
    return null;
  } catch (error) {
    const message =
      error instanceof ApiError ? error.message : restart ? "could not restart" : "could not resume";
    room.showNotice(message, "error");
    return message;
  }
}
