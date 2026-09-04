/** REST calls for a stopped jack's lifecycle, split from the at-cap core API. */

import { AttachmentSchema, OkResultSchema } from "./contracts";
import type { Attachment, OkResult } from "./contracts";
import { AttachmentFreshRequestSchema } from "./attachment-contracts";
import type { AttachmentFreshRequest } from "./attachment-contracts";
import { request } from "./api";

export const attachmentLifecycleApi = {
  /** New session, same handle; the server retires the old card on success. */
  fresh: (attachmentId: string, payload: AttachmentFreshRequest = {}): Promise<Attachment> =>
    request(`/api/attachments/${attachmentId}/fresh`, {
      schema: AttachmentSchema,
      method: "POST",
      body: AttachmentFreshRequestSchema.parse(payload),
      fallback: "could not start fresh",
    }),

  /** Forget a stopped jack: its card, token, and resumable session. Chat stays. */
  forget: (attachmentId: string): Promise<OkResult> =>
    request(`/api/attachments/${attachmentId}/record`, {
      schema: OkResultSchema,
      method: "DELETE",
      fallback: "could not remove from the roster",
    }),
};
