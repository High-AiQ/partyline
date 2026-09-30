import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import * as messageApi from "../lib/message-api";
import type { ChatMessage } from "../lib/contracts";
import { MessageHistory } from "./message-history.svelte";

function message(id: number): ChatMessage {
  return {
    id,
    conv_id: "line",
    sender: "greg",
    sender_type: "human",
    body: `message ${String(id)}`,
    created_at: id,
    files: [],
  };
}

function messages(first: number, last: number): ChatMessage[] {
  return Array.from({ length: last - first + 1 }, (_, index) => message(first + index));
}

afterEach(() => vi.restoreAllMocks());

describe("history jumps to pinned messages", () => {
  it("merges an old window with the live tail, dedupes ids, and pages newer", async () => {
    const history = new MessageHistory(() => "greg");
    history.seed(messages(101, 120), true);
    const around = vi.spyOn(messageApi, "messagesAround");
    around.mockResolvedValue({
      messages: messages(1, 21),
      has_more_before: false,
      has_more_after: true,
    });
    const page = vi.spyOn(api, "messagePage").mockResolvedValue({
      messages: messages(22, 41),
      has_more: true,
    });

    await history.jumpAround("line", 11);
    expect(history.messages.map((item) => item.id)).toEqual([
      ...Array.from({ length: 21 }, (_, index) => index + 1),
      ...Array.from({ length: 20 }, (_, index) => index + 101),
    ]);
    expect(history.highlightedId).toBe(11);
    expect(history.hasNewer).toBe(true);

    await history.loadNewer("line");
    expect(page).toHaveBeenCalledWith("line", { afterId: 21, limit: 20 });
    expect(history.messages.filter((item) => item.id === 21)).toHaveLength(1);
    expect(history.hasNewer).toBe(true);
    history.returnToLive();
    expect(history.jumpedAway).toBe(false);
  });

  it("scrolls to an already loaded target without requesting another window", async () => {
    const history = new MessageHistory(() => "greg");
    history.seed(messages(1, 20), false);
    const around = vi.spyOn(messageApi, "messagesAround");

    await history.jumpAround("line", 12);

    expect(around).not.toHaveBeenCalled();
    expect(history.highlightedId).toBe(12);
    expect(history.scrollRequest).toBe(1);
  });
});
