import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ConversationList from "./ConversationList.svelte";
import { room } from "../../state/room.svelte.js";

afterEach(() => {
  room.conversations = [];
  document.body.replaceChildren();
});

describe("conversation rail live state", () => {
  it("renders an accessible LED without adding the count to the visible label", async () => {
    room.conversations = [
      {
        id: "line",
        name: "Release line",
        topic: "",
        created_at: 1,
        archived_at: null,
        live_count: 2,
      },
    ];
    const list = mount(ConversationList, {
      target: document.body,
      props: {
        onmanagement: vi.fn(),
        onrename: vi.fn(),
        oncloseprocesses: vi.fn(),
        ondelete: vi.fn(),
      },
    });
    try {
      const indicator = document.querySelector(".line-live");
      expect(indicator).toBeInstanceOf(HTMLSpanElement);
      if (!(indicator instanceof HTMLSpanElement)) throw new Error("missing live indicator");
      expect(indicator.getAttribute("aria-label")).toBe("2 live");
      expect(indicator.querySelector(".led.running")).toBeInstanceOf(HTMLSpanElement);
      expect(document.querySelector(".conv-name")?.textContent).toBe("Release line");
      expect(document.querySelector(".conv")?.textContent.trim()).toBe("Release line");
    } finally {
      await unmount(list);
    }
  });
});

describe("conversation rail bulk select", () => {
  it("selects a subtree in select mode and hands the lines to bulk archive", async () => {
    room.conversations = [
      {
        id: "root",
        name: "root",
        topic: "",
        created_at: 1,
        archived_at: null,
        live_count: 0,
        parent_id: null,
      },
      {
        id: "kid",
        name: "kid",
        topic: "",
        created_at: 2,
        archived_at: null,
        live_count: 0,
        parent_id: "root",
      },
      {
        id: "solo",
        name: "solo",
        topic: "",
        created_at: 3,
        archived_at: null,
        live_count: 0,
        parent_id: null,
      },
    ];
    const open = vi.spyOn(room, "open").mockResolvedValue(undefined);
    const onarchivemany = vi.fn();
    const list = mount(ConversationList, {
      target: document.body,
      props: {
        onmanagement: vi.fn(),
        onrename: vi.fn(),
        oncloseprocesses: vi.fn(),
        ondelete: vi.fn(),
        onarchivemany,
      },
    });
    try {
      document.querySelector<HTMLButtonElement>(".bulk-select")?.click();
      await vi.waitFor(() => {
        expect(document.querySelectorAll(".bulk-check")).toHaveLength(3);
      });
      expect(document.querySelector(".conv-more")).toBeNull();
      document.querySelector<HTMLButtonElement>(".conv")?.click();
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("2 selected");
      });
      expect(open).not.toHaveBeenCalled();
      document.querySelector<HTMLButtonElement>(".bulk-archive")?.click();
      const [lines, done] = onarchivemany.mock.calls[0] as [{ id: string }[], () => void];
      expect(lines.map((line) => line.id)).toEqual(["root", "kid"]);
      done();
      await vi.waitFor(() => {
        expect(document.querySelector(".bulk-check")).toBeNull();
      });
    } finally {
      await unmount(list);
      vi.restoreAllMocks();
    }
  });
});
