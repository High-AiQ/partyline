/** Closed wire contracts for immutable structured review decisions. */

import { z } from "zod";

export const ReviewDecisionChoiceSchema = z.enum(["approve", "reject"]);
export type ReviewDecisionChoice = z.infer<typeof ReviewDecisionChoiceSchema>;

export const ReviewDecisionInSchema = z
  .object({
    presentation_message_id: z.number().int().positive(),
    decision: ReviewDecisionChoiceSchema,
  })
  .strict();
export type ReviewDecisionIn = z.infer<typeof ReviewDecisionInSchema>;

export const ReviewObservationSchema = z
  .object({
    conversation_id: z.string(),
    presentation_message_id: z.string(),
    evidence_kind: z.literal("decision"),
    evidence_ref: z.string(),
    sender_id: z.string(),
    decision: ReviewDecisionChoiceSchema,
    observed_at: z.string(),
  })
  .strict();
export type ReviewObservation = z.infer<typeof ReviewObservationSchema>;

export function senderIdForUser(userId: number): string {
  return `partyline-user-${String(userId)}`;
}
