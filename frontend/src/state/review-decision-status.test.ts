import { describe, expect, it } from "vitest";
import { reviewDecisionStatus } from "./review-decision-status.svelte.js";

describe("reviewDecisionStatus", () => {
  it("scopes badges to the authenticated user", () => {
    reviewDecisionStatus.entries = {};
    reviewDecisionStatus.record("conv-1", 10650, 1, "approve");
    expect(reviewDecisionStatus.get("conv-1", 10650, 1)).toBe("approve");
    expect(reviewDecisionStatus.get("conv-1", 10650, 2)).toBeNull();
  });
});
