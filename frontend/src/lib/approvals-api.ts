/** One-click approvals: every pending person-decision in a subtree, listed on the root line. */
import { z } from "zod";
import { request } from "./http";

export const ApprovalItemSchema = z.object({
  kind: z.string(),
  conv_id: z.string(),
  line: z.string(),
  request_id: z.string(),
  requester: z.string(),
  detail: z.string(),
  created_at: z.number(),
  approve: z.string(),
  decline: z.string(),
});
export type ApprovalItem = z.infer<typeof ApprovalItemSchema>;

export const ApprovalsListSchema = z.object({
  approvals: z.array(ApprovalItemSchema),
});
export type ApprovalsList = z.infer<typeof ApprovalsListSchema>;

export const approvalsApi = {
  list: (convId: string): Promise<ApprovalsList> =>
    request(`/api/conversations/${convId}/approvals`, { schema: ApprovalsListSchema }),
  decide: (item: ApprovalItem, approve: boolean): Promise<unknown> =>
    request(approve ? item.approve : item.decline, {
      method: approve ? "POST" : "DELETE",
      schema: z.unknown(),
      fallback: `could not ${approve ? "approve" : "decline"} the ${item.kind} request`,
    }),
};
