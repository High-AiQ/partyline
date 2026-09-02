import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ReviewDecisionDialog from "./ReviewDecisionDialog.svelte";
import { api, ApiError } from "../../lib/api";
import type { ChatMessage } from "../../lib/contracts";

const message: ChatMessage = {
  id: 10650,
  conv_id: "conv-1",
  sender: "sol",
  sender_type: "agent",
  body: "Phase 14 backend is ready for your review.",
  created_at: 1,
  files: [],
};

function clickButton(selector: string): void {
  const button = document.querySelector(selector);
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`missing ${selector}`);
  }
  button.click();
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ReviewDecisionDialog", () => {
  it("posts approve with a numeric presentation id", async () => {
    const create = vi.spyOn(api, "createReviewDecision").mockResolvedValue({
      conversation_id: "conv-1",
      presentation_message_id: "10650",
      evidence_kind: "decision",
      evidence_ref: "decision:source-uuid",
      sender_id: "partyline-user-1",
      decision: "approve",
      observed_at: "2026-09-02T22:15:00Z",
    });
    const close = vi.fn();
    const dialog = mount(ReviewDecisionDialog, {
      target: document.body,
      props: { message, conversationId: "conv-1", close },
    });
    try {
      clickButton("button.primary");
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("approve recorded");
      });
      expect(create).toHaveBeenCalledWith("conv-1", {
        presentation_message_id: 10650,
        decision: "approve",
      });
    } finally {
      await unmount(dialog);
    }
  });

  it("surfaces API failures without closing", async () => {
    vi.spyOn(api, "createReviewDecision").mockRejectedValue(new ApiError("network down", 503));
    const close = vi.fn();
    const dialog = mount(ReviewDecisionDialog, {
      target: document.body,
      props: { message, conversationId: "conv-1", close },
    });
    try {
      clickButton("button.danger");
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("network down");
      });
      expect(close).not.toHaveBeenCalled();
    } finally {
      await unmount(dialog);
    }
  });
});
