import { describe, expect, it, vi } from "vitest";
import { handleWireError } from "./room-wire-error";
import type { RefusalTarget } from "./room-wire-error";

function target() {
  const showNotice = vi.fn();
  const leave = vi.fn();
  const loadConversations = vi.fn().mockResolvedValue(undefined);
  const refreshArchiveIfOpen = vi.fn();
  const room: RefusalTarget = { showNotice, leave, loadConversations, refreshArchiveIfOpen };
  return { room, showNotice, leave, loadConversations, refreshArchiveIfOpen };
}

const event = (message: string) => ({ type: "error" as const, conversation_id: "conv", message });

describe("handleWireError", () => {
  it("leaves an archived line and refreshes both lists", () => {
    const { room, showNotice, leave, loadConversations, refreshArchiveIfOpen } = target();
    const context = { wasReady: true, claimRejected: false, rejectClaim: vi.fn() };
    handleWireError(room, event("this line was archived"), context);
    expect(leave).toHaveBeenCalledOnce();
    expect(loadConversations).toHaveBeenCalledOnce();
    expect(refreshArchiveIfOpen).toHaveBeenCalledOnce();
    expect(showNotice).toHaveBeenCalledWith("this line was archived", "error");
  });

  it("rejects the claim on a pre-handshake refusal instead of retrying forever", () => {
    const { room, leave } = target();
    const rejectClaim = vi.fn();
    handleWireError(room, event("handle is taken"), { wasReady: false, claimRejected: false, rejectClaim });
    expect(rejectClaim).toHaveBeenCalledOnce();
    expect(leave).not.toHaveBeenCalled();
  });

  it("only shows a notice for a refusal after the handshake, with a fallback message", () => {
    const { room, showNotice } = target();
    const rejectClaim = vi.fn();
    handleWireError(room, event(""), { wasReady: true, claimRejected: false, rejectClaim });
    expect(rejectClaim).not.toHaveBeenCalled();
    expect(showNotice).toHaveBeenCalledWith("this line is no longer available", "error");
  });
});
