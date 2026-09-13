/** Human-facing management controls share the server's explicit role boundary. */
import { z } from "zod";
import { request } from "./http";
import { ConversationSchema } from "./contracts";

export const LeadSchema = z.object({ attachment_id: z.string().nullable() });
export type Lead = z.infer<typeof LeadSchema>;

export const hierarchyApi = {
  setParent: (id: string, parentId: string | null) =>
    request(`/api/conversations/${id}/parent`, {
      schema: ConversationSchema,
      method: "PUT",
      body: { parent_id: parentId },
      fallback: "could not update parent line",
    }),
  /** The line's captain, if one is appointed. The server keeps calling the role `lead`. */
  lead: (id: string) =>
    request(`/api/conversations/${id}/lead`, { schema: LeadSchema, fallback: "could not load the captain" }),
  /** Appointing a captain rings it at once with the captain pack; the server refuses (403)
   *  anyone but a person or the current captain once a line has one. */
  appoint: (id: string, attachmentId: string | null) =>
    request(`/api/conversations/${id}/lead`, {
      schema: LeadSchema,
      method: "POST",
      body: { attachment_id: attachmentId },
      fallback: "could not appoint the captain",
    }),
};
