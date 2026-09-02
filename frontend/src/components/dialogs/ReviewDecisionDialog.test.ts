import { mount, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ReviewDecisionDialog from "./ReviewDecisionDialog.svelte";
import { api, ApiError } from "../../lib/api";
import type { ChatMessage } from "../../lib/contracts";
import { session } from "../../state/session.svelte.js";

const message: ChatMessage = {
  id: 10650,
  conv_id: "conv-1",
  sender: "sol",
  sender_type: "agent",
  body: "Phase 14 backend is ready for your review.",
  created_at: 1,
  files: [],
};

const observation = {
  conversation_id: "conv-1",
  presentation_message_id: "10650",
  evidence_kind: "decision" as const,
  evidence_ref: "decision:source-uuid",
  sender_id: "partyline-user-1",
  decision: "approve" as const,
  observed_at: "2026-09-02T22:15:00+00:00",
};

function clickButton(selector: string): void {
  const button = document.querySelector(selector);
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`missing ${selector}`);
  }
  button.click();
}

function clickClose(): void {
  const button = document.querySelector("button.close");
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error("missing close button");
  }
  button.click();
}

beforeEach(() => {
  session.authReady = true;
  session.user = { id: 1, email: "greg@example.com", handle: "greg" };
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("ReviewDecisionDialog", () => {
  it("posts approve with a numeric presentation id", async () => {
    const create = vi.spyOn(api, "createReviewDecision").mockResolvedValue(observation);
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

  it("refuses backdrop close while the POST is in flight", async () => {
    let resolveCreate!: (value: typeof observation) => void;
    const pending = new Promise<typeof observation>((resolve) => {
      resolveCreate = resolve;
    });
    vi.spyOn(api, "createReviewDecision").mockReturnValue(pending);
    const close = vi.fn();
    mount(ReviewDecisionDialog, {
      target: document.body,
      props: { message, conversationId: "conv-1", close },
    });
    clickButton("button.primary");
    await vi.waitFor(() => {
      expect(document.body.textContent).toContain("recording…");
    });
    clickClose();
    expect(close).not.toHaveBeenCalled();
    resolveCreate(observation);
    await vi.waitFor(() => {
      expect(document.body.textContent).toContain("approve recorded");
    });
  });

  it("clears the success timer when the dialog is destroyed", async () => {
    vi.useFakeTimers();
    vi.spyOn(api, "createReviewDecision").mockResolvedValue(observation);
    const close = vi.fn();
    const dialog = mount(ReviewDecisionDialog, {
      target: document.body,
      props: { message, conversationId: "conv-1", close },
    });
    clickButton("button.primary");
    await vi.waitFor(() => {
      expect(document.body.textContent).toContain("approve recorded");
    });
    await unmount(dialog);
    vi.advanceTimersByTime(2000);
    expect(close).not.toHaveBeenCalled();
  });
});
