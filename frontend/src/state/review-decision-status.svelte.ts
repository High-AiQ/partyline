/**
 * Local post-success review decisions for the signed-in human.
 *
 * The server is authoritative, but the UI deliberately avoids per-message GET
 * fan-out. After a successful POST, the choice is remembered for this session
 * and scoped to the authenticated user so a logout/login cannot inherit badges.
 */

import type { ReviewDecisionChoice } from "../lib/review-decisions";

class ReviewDecisionStatus {
  entries = $state<Record<string, ReviewDecisionChoice>>({});

  private key(conversationId: string, messageId: number, userId: number): string {
    return `${conversationId}:${String(messageId)}:${String(userId)}`;
  }

  get(conversationId: string, messageId: number, userId: number): ReviewDecisionChoice | null {
    return this.entries[this.key(conversationId, messageId, userId)] ?? null;
  }

  record(conversationId: string, messageId: number, userId: number, decision: ReviewDecisionChoice): void {
    this.entries = {
      ...this.entries,
      [this.key(conversationId, messageId, userId)]: decision,
    };
  }
}

export const reviewDecisionStatus = new ReviewDecisionStatus();
