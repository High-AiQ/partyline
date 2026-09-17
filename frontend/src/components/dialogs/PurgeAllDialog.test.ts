import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import PurgeAllDialog from "./PurgeAllDialog.svelte";
import { api } from "../../lib/api";
import { room } from "../../state/room.svelte.js";
import type { Conversation } from "../../lib/contracts";

function makeConv(id: string, name: string): Conversation {
  return {
    id,
    name,
    topic: "",
    created_at: 100,
    archived_at: 200,
    live_count: 0,
  };
}

describe("PurgeAllDialog", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.replaceChildren();
  });

  it("renders confirmation text with count, names, and permanent deletion warning", async () => {
    const convs = [makeConv("c1", "First Line"), makeConv("c2", "Second Line")];
    const close = vi.fn();
    const dialog = mount(PurgeAllDialog, {
      target: document.body,
      props: { conversations: convs, close },
    });

    try {
      const text = document.body.textContent;
      expect(text).toContain("2 archived lines");
      expect(text).toContain("First Line");
      expect(text).toContain("Second Line");
      expect(text.toLowerCase()).toContain("messages, files, and worktrees are deleted and cannot be undone");
    } finally {
      await unmount(dialog);
    }
  });

  it("calls api.purgeArchivedConversations, closes dialog, refreshes archive, and shows result toast", async () => {
    const convs = [makeConv("c1", "First Line"), makeConv("c2", "Second Line")];
    const close = vi.fn();
    const purgeSpy = vi.spyOn(api, "purgeArchivedConversations").mockResolvedValue({
      purged: ["c1", "c2"],
      skipped: [],
    });
    const loadArchivedSpy = vi.spyOn(room, "loadArchived").mockResolvedValue();
    const noticeSpy = vi.spyOn(room, "showNotice").mockReturnValue();

    const dialog = mount(PurgeAllDialog, {
      target: document.body,
      props: { conversations: convs, close },
    });

    try {
      const button = [...document.querySelectorAll("button")].find((b) =>
        b.textContent.includes("purge all"),
      );
      expect(button).toBeInstanceOf(HTMLButtonElement);
      if (!(button instanceof HTMLButtonElement)) throw new Error("missing purge all button");
      button.click();

      await vi.waitFor(() => {
        expect(purgeSpy).toHaveBeenCalledTimes(1);
        expect(close).toHaveBeenCalledTimes(1);
        expect(loadArchivedSpy).toHaveBeenCalledTimes(1);
        expect(noticeSpy).toHaveBeenCalledWith("purged 2 lines");
      });
    } finally {
      await unmount(dialog);
    }
  });

  it("includes skipped count in toast when lines were skipped", async () => {
    const convs = [makeConv("c1", "First Line"), makeConv("c2", "Child Line")];
    const close = vi.fn();
    vi.spyOn(api, "purgeArchivedConversations").mockResolvedValue({
      purged: ["c1"],
      skipped: [{ id: "c2", reason: "line has a child that is not archived" }],
    });
    vi.spyOn(room, "loadArchived").mockResolvedValue();
    const noticeSpy = vi.spyOn(room, "showNotice").mockReturnValue();

    const dialog = mount(PurgeAllDialog, {
      target: document.body,
      props: { conversations: convs, close },
    });

    try {
      const button = [...document.querySelectorAll("button")].find((b) =>
        b.textContent.includes("purge all"),
      );
      if (!(button instanceof HTMLButtonElement)) throw new Error("missing purge all button");
      button.click();

      await vi.waitFor(() => {
        expect(noticeSpy).toHaveBeenCalledWith("purged 1 line, 1 skipped");
      });
    } finally {
      await unmount(dialog);
    }
  });
});
