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

function page(first: number, last: number, hasMore: boolean) {
  return { messages: messages(first, last), has_more: hasMore };
}

afterEach(() => vi.restoreAllMocks());

describe("history jumps to pinned messages", () => {
  it("returns to a fresh live tail, then older paging can recover every message", async () => {
    const history = new MessageHistory(() => "greg");
    history.seed(messages(121, 140), true);
    vi.spyOn(messageApi, "messagesAround").mockResolvedValue({
      messages: messages(1, 11),
      has_more_before: false,
      has_more_after: true,
    });
    const pages = vi.spyOn(api, "messagePage").mockImplementation((_line, args) => {
      if (args?.afterId !== undefined) return Promise.resolve(page(12, 31, true));
      if (args?.beforeId === undefined) return Promise.resolve(page(121, 140, true));
      const first = Math.max(1, args.beforeId - 20);
      return Promise.resolve(page(first, args.beforeId - 1, first > 1));
    });

    await history.jumpAround("line", 1);
    expect(history.gaps).toEqual([{ afterId: 11, beforeId: 121 }]);
    await history.returnToLive("line");
    expect(history.messages.map((item) => item.id)).toEqual(Array.from({ length: 20 }, (_, i) => i + 121));
    while (history.hasOlder) await history.loadOlder("line");

    expect(history.messages.map((item) => item.id)).toEqual(Array.from({ length: 140 }, (_, i) => i + 1));
    expect(history.jumpedAway).toBe(false);
    expect(history.gaps).toEqual([]);
    expect(pages).toHaveBeenCalledWith("line", { limit: 20 });
  });

  it("keeps the missing-history control when jumping to another loaded message", async () => {
    const history = new MessageHistory(() => "greg");
    history.seed(messages(121, 140), true);
    const around = vi.spyOn(messageApi, "messagesAround").mockResolvedValue({
      messages: messages(1, 11),
      has_more_before: false,
      has_more_after: true,
    });

    await history.jumpAround("line", 1);
    await history.jumpAround("line", 5);

    expect(around).toHaveBeenCalledTimes(1);
    expect(history.hasNewer).toBe(true);
    expect(history.gaps).toEqual([{ afterId: 11, beforeId: 121 }]);
  });

  it("does not mark an overlapping around-window as a gap", async () => {
    const history = new MessageHistory(() => "greg");
    history.seed(messages(121, 140), true);
    vi.spyOn(messageApi, "messagesAround").mockResolvedValue({
      messages: messages(108, 128),
      has_more_before: true,
      has_more_after: true,
    });

    await history.jumpAround("line", 118);

    expect(history.messages.map((item) => item.id)).toEqual(Array.from({ length: 33 }, (_, i) => i + 108));
    expect(history.gaps).toEqual([]);
    expect(history.hasNewer).toBe(false);
  });

  it("splits gaps across repeated far jumps and fills both in order", async () => {
    const history = new MessageHistory(() => "greg");
    history.seed(messages(121, 140), true);
    vi.spyOn(messageApi, "messagesAround")
      .mockResolvedValueOnce({
        messages: messages(1, 11),
        has_more_before: false,
        has_more_after: true,
      })
      .mockResolvedValueOnce({
        messages: messages(50, 70),
        has_more_before: true,
        has_more_after: true,
      });
    const pages = vi.spyOn(api, "messagePage").mockImplementation((_line, args) => {
      const first = (args?.afterId ?? 0) + 1;
      const last = Math.min(first + 19, 140);
      return Promise.resolve(page(first, last, last < 140));
    });

    await history.jumpAround("line", 1);
    await history.jumpAround("line", 60);
    expect(history.gaps).toEqual([
      { afterId: 11, beforeId: 50 },
      { afterId: 70, beforeId: 121 },
    ]);

    await history.loadNewer("line", 11);
    expect(history.gaps).toEqual([{ afterId: 70, beforeId: 121 }]);
    await history.loadNewer("line", 70);
    expect(history.gaps).toEqual([{ afterId: 110, beforeId: 121 }]);
    await history.loadNewer("line", 110);

    expect(history.messages.map((item) => item.id)).toEqual(Array.from({ length: 140 }, (_, i) => i + 1));
    expect(history.gaps).toEqual([]);
    expect(pages).toHaveBeenCalledTimes(5);
  });

  it("limits one gap fill to two pages and advances the remaining gap", async () => {
    const history = new MessageHistory(() => "greg");
    history.seed(messages(19_981, 20_000), true);
    vi.spyOn(messageApi, "messagesAround").mockResolvedValue({
      messages: messages(1, 11),
      has_more_before: false,
      has_more_after: true,
    });
    const pages = vi.spyOn(api, "messagePage").mockImplementation((_line, args) => {
      const first = (args?.afterId ?? 0) + 1;
      return Promise.resolve(page(first, first + 19, true));
    });
    await history.jumpAround("line", 1);

    const added = await history.loadNewer("line", 11);

    expect(pages).toHaveBeenCalledTimes(2);
    expect(added).toBe(40);
    expect(history.gaps).toEqual([{ afterId: 51, beforeId: 19_981 }]);
    expect(history.messages).toHaveLength(71);
  });

  it("ignores a newer-page response after switching lines", async () => {
    const history = new MessageHistory(() => "greg");
    history.seed(messages(121, 140), true);
    vi.spyOn(messageApi, "messagesAround").mockResolvedValue({
      messages: messages(1, 11),
      has_more_before: false,
      has_more_after: true,
    });
    let resolvePage!: (value: ReturnType<typeof page>) => void;
    vi.spyOn(api, "messagePage").mockReturnValueOnce(
      new Promise((resolve) => {
        resolvePage = resolve;
      }),
    );
    await history.jumpAround("line", 1);
    const pending = history.loadNewer("line", 11);
    history.reset();
    history.seed(messages(201, 220), false);
    resolvePage(page(12, 31, true));
    await pending;

    expect(history.messages.map((item) => item.id)).toEqual(Array.from({ length: 20 }, (_, i) => i + 201));
    expect(history.loadingGapAfterId).toBeNull();
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
