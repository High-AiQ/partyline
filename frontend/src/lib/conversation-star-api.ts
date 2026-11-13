import { ConversationStarResponseSchema } from "./conversation-contracts";
import type { ConversationStarResponse } from "./conversation-contracts";
import { request } from "./http";

export function setConversationStar(id: string, starred: boolean): Promise<ConversationStarResponse> {
  return request(`/api/conversations/${encodeURIComponent(id)}/star`, {
    schema: ConversationStarResponseSchema,
    method: starred ? "PUT" : "DELETE",
    fallback: "could not update starred line",
  });
}
