/** Human-facing management controls share the server's explicit role boundary. */
import { request } from "./http";
import { ConversationSchema } from "./contracts";

export const hierarchyApi = {
  /** Managers are appointed by agents in chat; the human UI only links lines. */
  setParent: (id: string, parentId: string | null) =>
    request(`/api/conversations/${id}/parent`, {
      schema: ConversationSchema,
      method: "PUT",
      body: { parent_id: parentId },
      fallback: "could not update parent line",
    }),
};
