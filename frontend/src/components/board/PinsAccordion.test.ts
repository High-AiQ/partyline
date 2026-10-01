import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { pinAccordionStorageKey } from "../../lib/pin-accordion-state";
import { room } from "../../state/room.svelte.js";
import PinsAccordion from "./PinsAccordion.svelte";

const conversation = {
  id: "pins-test-line",
  name: "line",
  created_at: 1,
  topic: "",
  goal: "",
  cwd: null,
  archived_at: null,
  live_count: 0,
  parent_id: null,
};

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  room.conversation = null;
  room.pins.clear();
  document.body.replaceChildren();
});

describe("pinned message accordion", () => {
  it("remembers collapse per line and shows aliased clipped text with local tooltips", async () => {
    room.conversation = conversation;
    room.pins.replace([
      {
        conversation_id: conversation.id,
        message_id: 88,
        alias:
          "A carefully written alias that is intentionally much longer than the narrow sidebar can show in one line",
        created_at: 1,
        message_available: true,
        message_text: "Original message body should be replaced by its alias",
        file_count: 0,
      },
    ]);
    const view = mount(PinsAccordion, { target: document.body });
    try {
      await Promise.resolve();
      const details = document.querySelector("details");
      expect(details?.open).toBe(true);
      const summary = document.querySelector("summary");
      summary?.click();
      details?.dispatchEvent(new Event("toggle"));
      expect(details?.open).toBe(false);
      expect(localStorage.getItem(pinAccordionStorageKey(conversation.id))).toBe("true");

      const label = document.querySelector("[data-pin-row] .line-clamp-2");
      expect(label?.textContent).toContain("A carefully written alias");
      expect(label?.textContent).not.toContain("Original message body");
      expect(label?.classList.contains("line-clamp-2")).toBe(true);
      expect(label?.getAttribute("aria-describedby")).toBeTruthy();
      const rowContent = document.querySelector("[data-pin-row] button > .flex");
      expect(rowContent?.querySelector("svg")).not.toBeNull();
      expect(rowContent?.querySelector(".line-clamp-2")).not.toBeNull();
      expect(document.querySelector("[data-pin-row]")?.hasAttribute("aria-describedby")).toBe(false);
      expect(
        document.querySelector('[aria-label="edit pin alias"]')?.getAttribute("aria-describedby"),
      ).toBeTruthy();
      expect(
        document.querySelector('[aria-label="remove pin"]')?.getAttribute("aria-describedby"),
      ).toBeTruthy();
    } finally {
      await unmount(view);
    }
  });

  it("uses the source message when a pin has no alias and restores saved state", async () => {
    localStorage.setItem(pinAccordionStorageKey(conversation.id), "true");
    room.conversation = conversation;
    room.pins.replace([
      {
        conversation_id: conversation.id,
        message_id: 12,
        alias: null,
        created_at: 1,
        message_available: true,
        message_text:
          "A long source message that should clip in the pin row but remain available in its tooltip\n📎 [file digest]",
        file_count: 1,
      },
    ]);
    const view = mount(PinsAccordion, { target: document.body });
    try {
      await Promise.resolve();
      expect(document.querySelector("details")?.open).toBe(false);
      const label = document.querySelector("[data-pin-row] .line-clamp-1");
      expect(label?.textContent).toContain("A long source message");
      expect(label?.textContent).not.toContain("[file digest]");
      expect(label?.classList.contains("line-clamp-1")).toBe(true);
    } finally {
      await unmount(view);
    }
  });

  it("renders and toggles when local storage is unavailable", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    room.conversation = conversation;
    const view = mount(PinsAccordion, { target: document.body });
    try {
      await Promise.resolve();
      const details = document.querySelector("details");
      expect(details?.open).toBe(true);
      details?.querySelector("summary")?.click();
      details?.dispatchEvent(new Event("toggle"));
      expect(details?.open).toBe(false);
    } finally {
      await unmount(view);
    }
  });
});
