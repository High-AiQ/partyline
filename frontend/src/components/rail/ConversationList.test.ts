import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ConversationList from "./ConversationList.svelte";
import { screenStatus } from "../../state/screen-status.svelte";
import { tick } from "svelte";
import { room } from "../../state/room.svelte.js";
import * as starState from "../../state/conversation-star";

function props() {
  return { onmanagement: vi.fn(), onrename: vi.fn(), oncloseprocesses: vi.fn(), ondelete: vi.fn() };
}

function star(label: string): HTMLButtonElement {
  const found = document.querySelector<HTMLButtonElement>(`.conv-star[aria-label="${label}"]`);
  if (!found) throw new Error(`missing star ${label}`);
  return found;
}

afterEach(() => {
  localStorage.clear();
  room.conversations = [];
  room.conversation = null;
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
        "Other",
      ]);
      expect([...document.querySelectorAll("h2")].map((heading) => heading.textContent.trim())).toEqual([
        "▾Starred",
        "▾Lines",
      ]);
      expect(
        document
          .querySelector<HTMLButtonElement>('[aria-label="Unstar Child"]')
          ?.getAttribute("aria-pressed"),
      ).toBe("true");
    } finally {
      await unmount(list);
    }
  });

  it("shows an inline star left of the name: outlined when unstarred, filled gold when starred", async () => {
    const base = { topic: "", created_at: 1, archived_at: null, live_count: 0 };
    room.conversations = [
      { ...base, id: "plain", name: "Plain" },
      { ...base, id: "kept", name: "Kept", starred: true, task_status: "implementing", task_mode: "full" },
    ];
    const list = mount(ConversationList, { target: document.body, props: props() });
    try {
      const outlined = star("Star Plain");
      expect(outlined.getAttribute("aria-pressed")).toBe("false");
      expect(outlined.querySelector("svg")?.getAttribute("fill")).toBe("none");
      expect(outlined.className).toContain("text-cream-faint");
      const filled = star("Unstar Kept");
      expect(filled.getAttribute("aria-pressed")).toBe("true");
      expect(filled.querySelector("svg")?.getAttribute("fill")).toBe("currentColor");
      expect(filled.className).toContain("text-gold");
      // Inside the row, not the actions cluster, and before both the kind icon and the name.
      const row = filled.closest(".conv-row");
      const slot = row?.querySelector(".star-slot");
      expect(filled.closest(".conv-actions")).toBeNull();
      expect(document.querySelectorAll(".conv-star")).toHaveLength(3);
      const mode = row?.querySelector(".task-mode");
      const name = row?.querySelector(".conv-name");
      if (!slot || !mode || !name) throw new Error("missing star slot, kind icon or name");
      // The star floats over this slot, which precedes the kind icon and the name.
      expect(slot.compareDocumentPosition(mode) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(slot.compareDocumentPosition(name) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      // Every row reserves the same slot, so the name never shifts with the star state.
      const slots = [...document.querySelectorAll(".star-slot")];
      expect(slots).toHaveLength(3);
      expect(new Set(slots.map((slot) => slot.className)).size).toBe(1);
    } finally {
      await unmount(list);
    }
  });

  it("toggles the star from a keyboard-focusable button without opening or selecting the line", async () => {
    room.conversations = [
      { id: "line", name: "Line", topic: "", created_at: 1, archived_at: null, live_count: 0 },
    ];
    const toggleStar = vi.spyOn(starState, "toggleConversationStar").mockResolvedValue(undefined);
    const open = vi.spyOn(room, "open").mockResolvedValue(undefined);
    const list = mount(ConversationList, { target: document.body, props: props() });
    try {
      const button = star("Star Line");
      expect(button.type).toBe("button");
      button.focus();
      await tick();
      expect(document.activeElement).toBe(button);
      button.click();
      expect(toggleStar).toHaveBeenCalledWith(room, "line");
      expect(open).not.toHaveBeenCalled();
      expect(document.querySelector(".conv.active")).toBeNull();
    } finally {
      await unmount(list);
      vi.restoreAllMocks();
    }
  });

  it("does not toggle selection when the star is clicked in select mode", async () => {
    room.conversations = [
      { id: "line", name: "Line", topic: "", created_at: 1, archived_at: null, live_count: 0 },
    ];
    vi.spyOn(starState, "toggleConversationStar").mockResolvedValue(undefined);
    const list = mount(ConversationList, {
      target: document.body,
      props: { ...props(), onarchivemany: vi.fn() },
    });
    try {
      document.querySelector<HTMLButtonElement>(".bulk-select")?.click();
      await tick();
      star("Star Line").click();
      await tick();
      expect(document.body.textContent).toContain("0 selected");
    } finally {
      await unmount(list);
      vi.restoreAllMocks();
    }
  });

  it("highlights the selected line in both the starred shortcut and main tree", async () => {
    const root = {
      id: "root",
      name: "Root",
      topic: "",
      created_at: 1,
      archived_at: null,
      live_count: 0,
      starred: true,
    };
    const child = {
      id: "child",
      name: "Child",
      topic: "",
      created_at: 2,
      archived_at: null,
      live_count: 0,
      parent_id: "root",
    };
    room.conversations = [root, child];
    room.conversation = child;
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
      await tick();
      expect(
        [...document.querySelectorAll(".conv.active .conv-name")].map((name) => name.textContent.trim()),
      ).toEqual(["Child", "Child"]);
    } finally {
      await unmount(list);
    }
  });
});

describe("collapsible rail groups", () => {
  const base = { topic: "", created_at: 1, archived_at: null, live_count: 0 };
  const names = () => [...document.querySelectorAll(".conv-name")].map((name) => name.textContent.trim());
  const header = (group: string) =>
    document.querySelector<HTMLButtonElement>(`.group-toggle[aria-label$="${group} group"]`);

  it("collapses the Starred and Lines groups independently and remembers it across a remount", async () => {
    room.conversations = [
      { ...base, id: "a", name: "Alpha", starred: true },
      { ...base, id: "b", name: "Beta" },
    ];
    let list = mount(ConversationList, { target: document.body, props: props() });
    try {
      expect(names()).toEqual(["Alpha", "Alpha", "Beta"]);
      expect(header("Starred")?.getAttribute("aria-expanded")).toBe("true");
      header("Starred")?.click();
      await tick();
      expect(names()).toEqual(["Alpha", "Beta"]);
      expect(header("Starred")?.getAttribute("aria-expanded")).toBe("false");
      expect(header("Starred")?.textContent).toContain("▸");
      header("Lines")?.click();
      await tick();
      expect(names()).toEqual([]);
      expect([...document.querySelectorAll("h2")].map((heading) => heading.textContent.trim())).toEqual([
        "▸Starred",
        "▸Lines",
      ]);
      await unmount(list);
      document.body.replaceChildren();
      list = mount(ConversationList, { target: document.body, props: props() });
      expect(names()).toEqual([]);
      header("Starred")?.click();
      await tick();
      expect(names()).toEqual(["Alpha"]);
      header("Lines")?.click();
      await tick();
      expect(names()).toEqual(["Alpha", "Alpha", "Beta"]);
    } finally {
      await unmount(list);
    }
  });

  it("never hides the whole list behind a Lines header that is not shown", async () => {
    localStorage.setItem("partyline_collapsed_rail_groups", JSON.stringify(["main"]));
    room.conversations = [{ ...base, id: "b", name: "Beta" }];
    const list = mount(ConversationList, { target: document.body, props: props() });
    try {
      expect(document.querySelector("h2")).toBeNull();
      expect(names()).toEqual(["Beta"]);
    } finally {
      await unmount(list);
    }
  });

  it("expands and collapses a starred line's subtree from the Starred group, sharing the main list's state", async () => {
    room.conversations = [
      { ...base, id: "root", name: "Root", starred: true },
      { ...base, id: "kid", name: "Kid", parent_id: "root" },
    ];
    const list = mount(ConversationList, { target: document.body, props: props() });
    try {
      const starredToggle = () =>
        document.querySelector<HTMLButtonElement>('.tree-toggle[aria-label$="sublines of Root"]');
      expect(names()).toEqual(["Root", "Root"]);
      expect(starredToggle()?.getAttribute("aria-expanded")).toBe("false");
      starredToggle()?.click();
      await tick();
      // One shared expand state: both the shortcut and the main tree show the child now.
      expect(names()).toEqual(["Root", "Kid", "Root", "Kid"]);
      expect(starredToggle()?.getAttribute("aria-expanded")).toBe("true");
      starredToggle()?.click();
      await tick();
      expect(names()).toEqual(["Root", "Root"]);
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
      const slot = rows[0]?.querySelector(".conv-name")?.parentElement?.previousElementSibling;
      expect(slot?.className).toContain("star-slot");
      expect(slot?.previousElementSibling?.className).toBe(live.parentElement?.className);
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
