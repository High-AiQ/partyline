/** Apply lifecycle responses even when the socket is reconnecting. */
import { ApiError, api } from "../lib/api";
import { attachmentLifecycleApi } from "../lib/attachment-lifecycle-api";
import { room } from "./room.svelte.js";

export async function activateJack(attachmentId: string, restart: boolean): Promise<void> {
  try {
    room.upsertAttachment(
      await (restart ? attachmentLifecycleApi.fresh(attachmentId, {}) : api.resume(attachmentId)),
    );
  } catch (error) {
    room.showNotice(
      error instanceof ApiError ? error.message : restart ? "could not restart" : "could not resume",
      "error",
    );
  }
}
