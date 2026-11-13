import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ConversationList from "./ConversationList.svelte";
import { screenStatus } from "../../state/screen-status.svelte";
import { tick } from "svelte";
import { room } from "../../state/room.svelte.js";
import * as starState from "../../state/conversation-star";

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
      const name = document.querySelector(".conv-name");
      if (!name) throw new Error("missing line name");
      expect(indicator.compareDocumentPosition(name)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
      expect(indicator.querySelector(".led.running")).toBeInstanceOf(HTMLSpanElement);
      expect(document.querySelector(".conv-name")?.textContent).toBe("Release line");
      expect(document.querySelector(".conv")?.textContent.trim()).toBe("Release line");
    } finally {
      await unmount(list);
    }
  });
});

describe("starred conversation rail", () => {
  it("pins starred rows in normal order and reflects a live list refresh", async () => {
    const base = { topic: "", created_at: 1, archived_at: null, live_count: 0 };
    room.conversations = [
      { ...base, id: "first", name: "First" },
      { ...base, id: "child", name: "Child", parent_id: "first" },
      { ...base, id: "other", name: "Other" },
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
      room.conversations = room.conversations.map((line) =>
        line.id === "child" || line.id === "other" ? { ...line, starred: true } : line,
      );
      await tick();
      expect([...document.querySelectorAll(".conv-name")].map((name) => name.textContent.trim())).toEqual([
        "Child",
        "Other",
        "First",
      ]);
      expect(document.querySelector("h2")?.textContent).toBe("Starred");
      expect(
        document
          .querySelector<HTMLButtonElement>('[aria-label="Unstar Child"]')
          ?.getAttribute("aria-pressed"),
      ).toBe("true");
    } finally {
      await unmount(list);
    }
  });

  it("makes the row star keyboard discoverable and calls the shared toggle action", async () => {
    room.conversations = [
      {
        id: "line",
        name: "Line",
        topic: "",
        created_at: 1,
        archived_at: null,
        live_count: 0,
      },
    ];
    const toggleStar = vi.spyOn(starState, "toggleConversationStar").mockResolvedValue(undefined);
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
      const star = document.querySelector<HTMLButtonElement>('[aria-label="Star Line"]');
      expect(star?.getAttribute("aria-pressed")).toBe("false");
      star?.focus();
      await tick();
      expect(document.activeElement).toBe(star);
      expect(document.querySelector(".conv-actions")?.className).toContain("group-focus-within:opacity-100");
      star?.click();
      expect(toggleStar).toHaveBeenCalledWith(room, "line");
    } finally {
      await unmount(list);
      vi.restoreAllMocks();
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
        live_count: 1,
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
      document.querySelector<HTMLButtonElement>(".tree-toggle")?.click();
      document.querySelector<HTMLButtonElement>(".bulk-select")?.click();
      await vi.waitFor(() => {
        expect(document.querySelectorAll(".bulk-check")).toHaveLength(3);
      });
      const rows = document.querySelectorAll(".conv");
      const child = rows[1];
      const check = child?.querySelector(".bulk-check");
      const marker = child?.querySelector('[aria-label="child line"]');
      const live = child?.querySelector(".line-live");
      const name = child?.querySelector(".conv-name");
      if (!check || !marker || !live || !name) throw new Error("missing child row elements");
      expect(check.compareDocumentPosition(marker)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
      expect(marker.compareDocumentPosition(live)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
      expect(live.compareDocumentPosition(name)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
      expect(rows[0]?.querySelector(".line-live")).toBeNull();
      expect(rows[0]?.querySelector(".conv-name")?.parentElement?.previousElementSibling?.className).toBe(
        live.parentElement?.className,
      );
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

describe("conversation rail task mode marker", () => {
  it("marks each task line with its mode and leaves other lines bare", async () => {
    const base = { topic: "", created_at: 1, archived_at: null, live_count: 0 };
    room.conversations = [
      { ...base, id: "e", name: "mock", task_status: "implementing", task_mode: "express" },
      { ...base, id: "l", name: "typo", task_status: "in_review", task_mode: "light" },
      { ...base, id: "f", name: "feature", task_status: "done", task_mode: "full" },
      { ...base, id: "p", name: "plain" },
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
      const labels = [...document.querySelectorAll(".task-mode")].map((item) =>
        item.getAttribute("aria-label"),
      );
      expect(labels.sort()).toEqual([
        "Express task: no review, no gates",
        "Full task: review and every gate",
        "Light task: review, gates scale with the diff",
      ]);
      const plain = [...document.querySelectorAll(".conv-row")].find((row) =>
        row.textContent.includes("plain"),
      );
      expect(plain?.querySelector(".task-mode")).toBeNull();
    } finally {
      await unmount(list);
    }
  });
});

describe("active share indicators", () => {
  it("shows a single labelled icon only on lines with an active share", async () => {
    const interval = vi.spyOn(globalThis, "setInterval");
    const base = { topic: "", created_at: 1, archived_at: null, live_count: 0 };
    room.conversations = [
      { ...base, id: "a", name: "A" },
      { ...base, id: "b", name: "B" },
    ];
    screenStatus.indicators = [
      { conv_id: "a", device_name: "Desk", kind: "screen", label: "Desk screen share" },
      { conv_id: "a", device_name: "Desk", kind: "window", label: "reading Editor for @bot" },
    ];
    const list = mount(ConversationList, {
      target: document.body,
      props: { onmanagement: vi.fn(), onrename: vi.fn(), oncloseprocesses: vi.fn(), ondelete: vi.fn() },
    });
    try {
      await tick();
      await Promise.resolve();
      await tick();
      const icons = document.querySelectorAll(".share-icon");
      expect(interval).not.toHaveBeenCalled();
      expect(icons).toHaveLength(1);
      expect(icons[0]?.getAttribute("aria-label")).toBe("Desk screen share; reading Editor for @bot");
      screenStatus.indicators = [];
      await tick();
      await Promise.resolve();
      await tick();
      expect(document.querySelectorAll(".share-icon")).toHaveLength(0);
    } finally {
      await unmount(list);
      vi.restoreAllMocks();
    }
  });
});
