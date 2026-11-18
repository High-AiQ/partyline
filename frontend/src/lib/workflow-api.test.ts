import { describe, expect, it } from "vitest";
import { workflowPreviewIsClean, workflowPreviewLabel, type WorkflowPreviewStep } from "./workflow-api";

describe("workflowPreviewLabel", () => {
  it("shows match counts and unresolved preconditions without dumping raw JSON", () => {
    const step: WorkflowPreviewStep = {
      step: "save",
      state: "multiply_matched",
      match_count: 2,
      ambiguous: false,
      multiply_matched: true,
      preconditions: [
        {
          state: "resolved",
          match_count: 1,
          ambiguous: false,
          multiply_matched: false,
          verdict: true,
        },
        {
          state: "missing",
          match_count: 0,
          ambiguous: false,
          multiply_matched: false,
          verdict: null,
        },
      ],
    };
    expect(workflowPreviewLabel(step)).toBe("multiply_matched · 2 matches · 1 precondition unresolved");
    expect(workflowPreviewIsClean(step)).toBe(false);
  });

  it("reports false preconditions separately from unresolved ones", () => {
    expect(
      workflowPreviewLabel({
        step: "remove-optional-row",
        state: "resolved",
        match_count: 1,
        ambiguous: false,
        multiply_matched: false,
        preconditions: [
          {
            state: "resolved",
            match_count: 1,
            ambiguous: false,
            multiply_matched: false,
            verdict: false,
          },
        ],
      }),
    ).toBe("resolved · 1 matches · 1 precondition violated");
  });

  it("considers a satisfied absence check clean", () => {
    expect(
      workflowPreviewIsClean({
        step: "optional-row",
        state: "resolved",
        match_count: 1,
        ambiguous: false,
        multiply_matched: false,
        preconditions: [
          {
            state: "resolved",
            match_count: 0,
            ambiguous: false,
            multiply_matched: false,
            verdict: true,
          },
        ],
      }),
    ).toBe(true);
  });
});
