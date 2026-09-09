/** Human-facing management controls share the server's explicit role boundary. */
import { z } from "zod";
import { request } from "./http";
import { ConversationSchema } from "./contracts";

export const LeadStateSchema = z.object({ attachment_id: z.string().nullable() });
export type LeadState = z.infer<typeof LeadStateSchema>;

export const hierarchyApi = {
  lead: (id: string): Promise<LeadState> =>
    request(`/api/conversations/${id}/lead`, { schema: LeadStateSchema }),
  setLead: (id: string, attachmentId: string | null): Promise<LeadState> =>
    request(`/api/conversations/${id}/lead`, {
      schema: LeadStateSchema,
      method: "POST",
      body: { attachment_id: attachmentId },
      fallback: "could not update manager",
    }),
  setParent: (id: string, parentId: string | null) =>
    request(`/api/conversations/${id}/parent`, {
      schema: ConversationSchema,
      method: "PUT",
      body: { parent_id: parentId },
      fallback: "could not update parent line",
    }),
};
