import { describe, expect, it } from "vitest";
import { ReviewDecisionInSchema, ReviewObservationSchema, senderIdForUser } from "./review-decisions";

describe("review decision contracts", () => {
  it("accepts the frozen POST body with a numeric presentation id", () => {
    expect(
      ReviewDecisionInSchema.parse({
        presentation_message_id: 10650,
        decision: "approve",
      }),
    ).toEqual({ presentation_message_id: 10650, decision: "approve" });
  });

  it("rejects string presentation ids and extra keys", () => {
    expect(() =>
      ReviewDecisionInSchema.parse({
        presentation_message_id: "10650",
        decision: "approve",
      }),
    ).toThrow();
    expect(() =>
      ReviewDecisionInSchema.parse({
        presentation_message_id: 10650,
        decision: "approve",
        sender_id: "partyline-user-1",
      }),
    ).toThrow();
  });

  it("locks the seven-field observation row", () => {
    const row = ReviewObservationSchema.parse({
      conversation_id: "line",
      presentation_message_id: "10650",
      evidence_kind: "decision",
      evidence_ref: "decision:source-uuid",
      sender_id: "partyline-user-42",
      decision: "reject",
      observed_at: "2026-09-02T22:15:00Z",
    });
    expect(row.evidence_kind).toBe("decision");
    expect(senderIdForUser(42)).toBe("partyline-user-42");
  });
});
