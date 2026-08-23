import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import type { ChatMessage } from "../lib/contracts";
import { MessageHistory } from "./message-history.svelte";

function message(id: number, sender = "greg"): ChatMessage {
  return {
    id,
    conv_id: "line",
    sender,
    sender_type: "human",
    body: `message ${String(id)}`,
    created_at: id,
    files: [],
  };
}

function messages(first: number, last: number): ChatMessage[] {
  return Array.from({ length: last - first + 1 }, (_, index) => message(first + index));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("paginated message history", () => {
  it("prepends an older page in order and remembers when history is exhausted", async () => {
    const history = new MessageHistory(() => "operator");
    history.seed(messages(21, 40), true);
    const messagePage = vi
      .spyOn(api, "messagePage")
      .mockResolvedValue({ messages: messages(1, 20), has_more: false });

    await expect(history.loadOlder("line")).resolves.toBe(20);

    expect(history.messages.map((item) => item.id)).toEqual(
      Array.from({ length: 40 }, (_, index) => index + 1),
    );
    expect(history.hasOlder).toBe(false);
    expect(history.humans.has("greg")).toBe(true);
    expect(messagePage).toHaveBeenCalledWith("line", { beforeId: 21, limit: 20 });
  });

  it("catches up every unseen page while deduping the newest detail page", async () => {
    const history = new MessageHistory(() => "operator");
    history.seed(messages(1, 20), false);
    history.merge(messages(26, 45));
    const messagePage = vi
      .spyOn(api, "messagePage")
      .mockResolvedValueOnce({ messages: messages(21, 40), has_more: true })
      .mockResolvedValueOnce({ messages: messages(41, 45), has_more: false });

    await history.catchUp("line", 20);

    expect(history.messages.map((item) => item.id)).toEqual(
      Array.from({ length: 45 }, (_, index) => index + 1),
    );
    expect(messagePage).toHaveBeenNthCalledWith(1, "line", { afterId: 20, limit: 20 });
    expect(messagePage).toHaveBeenNthCalledWith(2, "line", { afterId: 40, limit: 20 });
  });

  it("drops an older response that belongs to a line left during the fetch", async () => {
    let release: ((page: { messages: ChatMessage[]; has_more: boolean }) => void) | undefined;
    vi.spyOn(api, "messagePage").mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    const history = new MessageHistory(() => "operator");
    history.seed(messages(21, 40), true);

    const pending = history.loadOlder("line");
    history.reset();
    release?.({ messages: messages(1, 20), has_more: false });

    await expect(pending).resolves.toBe(0);
    expect(history.messages).toEqual([]);
    expect(history.loadingOlder).toBe(false);
  });

  it("keeps the older boundary retryable after a network failure", async () => {
    const history = new MessageHistory(() => "operator");
    history.seed(messages(21, 40), true);
    vi.spyOn(api, "messagePage").mockRejectedValue(new Error("offline"));

    await expect(history.loadOlder("line")).rejects.toThrow("offline");

    expect(history.hasOlder).toBe(true);
    expect(history.olderError).toBe(true);
    expect(history.loadingOlder).toBe(false);
  });
});
