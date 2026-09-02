/** POST one immutable structured review decision for a presentation message. */

import { request } from "./http";
import {
  ReviewDecisionInSchema,
  ReviewObservationSchema,
  type ReviewDecisionIn,
  type ReviewObservation,
} from "./review-decisions";

export function createReviewDecision(
  conversationId: string,
  payload: ReviewDecisionIn,
): Promise<ReviewObservation> {
  return request(`/api/conversations/${conversationId}/review-decisions`, {
    schema: ReviewObservationSchema,
    method: "POST",
    body: ReviewDecisionInSchema.parse(payload),
    fallback: "could not record review decision",
  });
}
