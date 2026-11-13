import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ConversationList from "./ConversationList.svelte";
import { screenStatus } from "../../state/screen-status.svelte";
import { tick } from "svelte";
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

describe("conversation rail chapter chain", () => {
  it("shows a quiet ch N on a continuing line and → on the one it continues", async () => {
    const base = { topic: "", created_at: 1, archived_at: null, live_count: 0 };
    room.conversations = [
      { ...base, id: "b", name: "Act two", chapter_of: "a", chapter: 2 },
      { ...base, id: "a", name: "Plan" },
      { ...base, id: "c", name: "Other" },
    ];
    const list = mount(ConversationList, {
      target: document.body,
      props: { onmanagement: vi.fn(), onrename: vi.fn(), oncloseprocesses: vi.fn(), ondelete: vi.fn() },
    });
    try {
      const rows = [...document.querySelectorAll(".conv-row")];
      const row = (name: string) =>
        rows.find((item) => item.querySelector(".conv-name .truncate")?.textContent.trim() === name);
      expect(row("Act two")?.querySelector(".chapter-mark")?.textContent).toBe("ch 2");
      expect(row("Act two")?.querySelector(".chapter-next")).toBeNull();
      expect(row("Plan")?.querySelector(".chapter-mark")).toBeNull();
      const next = [...document.querySelectorAll(".chapter-next")];
      expect(next).toHaveLength(1);
      expect(next[0]?.getAttribute("aria-label")).toBe("continued in Act two");
      expect(row("Other")?.querySelector(".chapter-mark, .chapter-next")).toBeNull();
    } finally {
      await unmount(list);
    }
  });

  it("offers new chapter in the line menu, but not on a task line", async () => {
    const base = { topic: "", created_at: 1, archived_at: null, live_count: 0 };
    room.conversations = [
      { ...base, id: "a", name: "Plan" },
      { ...base, id: "t", name: "Task", task_status: "implementing" },
    ];
    const onchapter = vi.fn();
    const list = mount(ConversationList, {
      target: document.body,
      props: {
        onmanagement: vi.fn(),
        onrename: vi.fn(),
        onchapter,
        oncloseprocesses: vi.fn(),
        ondelete: vi.fn(),
      },
    });
    try {
      const more = (name: string) =>
        document.querySelector<HTMLButtonElement>(`.conv-more[aria-label="line actions for ${name}"]`);
      more("Task")?.click();
      await tick();
      expect(document.querySelector(".new-chapter")).toBeNull();
      more("Task")?.click(); // toggle the menu closed
      more("Plan")?.click();
      await tick();
      document.querySelector<HTMLButtonElement>(".new-chapter")?.click();
      expect(onchapter).toHaveBeenCalledWith(expect.objectContaining({ id: "a" }));
    } finally {
      await unmount(list);
    }
  });
});
