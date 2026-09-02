/**
 * Local post-success review decisions for the signed-in human.
 *
 * The server is authoritative, but the UI deliberately avoids per-message GET
 * fan-out. After a successful POST, the choice is remembered for this session.
 */

import type { ReviewDecisionChoice } from "../lib/review-decisions";

class ReviewDecisionStatus {
  entries = $state<Record<string, ReviewDecisionChoice>>({});

  private key(conversationId: string, messageId: number): string {
    return `${conversationId}:${String(messageId)}`;
  }

  get(conversationId: string, messageId: number): ReviewDecisionChoice | null {
    return this.entries[this.key(conversationId, messageId)] ?? null;
  }

  record(conversationId: string, messageId: number, decision: ReviewDecisionChoice): void {
    this.entries = { ...this.entries, [this.key(conversationId, messageId)]: decision };
  }
}

export const reviewDecisionStatus = new ReviewDecisionStatus();
