import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import Reactions from "./Reactions.svelte";

afterEach(() => {
  vi.restoreAllMocks();
});

function allowTooltips(): void {
  vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("message reactions", () => {
  it("renders the picker and existing chips with accessible controls", async () => {
    allowTooltips();
    const onToggle = vi.fn().mockResolvedValue(undefined);
    const component = mount(Reactions, {
      target: document.body,
      props: {
        messageId: 7,
        reactions: [{ emoji: "✅", reactors: ["greg", "sol"], mine: true }],
        onToggle,
      },
    });
    flushSync();
    try {
      expect(document.querySelector('[aria-label="Reaction picker"]')).not.toBeNull();
      const choices = Array.from(document.querySelectorAll<HTMLButtonElement>(".reaction-choice"));
      expect(choices.some((button) => button.getAttribute("aria-label") === "React with 👍")).toBe(true);
      expect(document.querySelector('[aria-label*="Toggle ✅ reaction"]')?.textContent).toContain("2");
      const chip = document.querySelector<HTMLButtonElement>(".reaction-chip");
      const chipTip = document.getElementById(chip?.getAttribute("aria-describedby") ?? "");
      chip?.dispatchEvent(new MouseEvent("mouseenter"));
      expect(chipTip?.hidden).toBe(false);
      expect(chipTip?.textContent).toBe("greg, sol");
    } finally {
      await unmount(component);
    }
  });

  it("labels the trigger through the tooltip action, not a native title", async () => {
    allowTooltips();
    const component = mount(Reactions, {
      target: document.body,
      props: { messageId: 7, reactions: [], onToggle: vi.fn().mockResolvedValue(undefined) },
    });
    flushSync();
    try {
      const trigger = document.querySelector<HTMLButtonElement>(".reaction-add");
      expect(trigger?.getAttribute("title")).toBeNull();
      expect(trigger?.getAttribute("aria-label")).toBe("react to this");
      trigger?.dispatchEvent(new FocusEvent("focus"));
      const tip = document.getElementById(trigger?.getAttribute("aria-describedby") ?? "");
      expect(tip?.hidden).toBe(false);
      expect(tip?.textContent).toBe("react to this");
      expect(tip?.getAttribute("role")).toBe("tooltip");
      trigger?.dispatchEvent(new FocusEvent("blur"));
      expect(tip?.hidden).toBe(true);
    } finally {
      await unmount(component);
    }
  });

  it("toggles a reaction from a keyboard-reachable picker button", async () => {
    const onToggle = vi.fn().mockResolvedValue(undefined);
    const component = mount(Reactions, {
      target: document.body,
      props: { messageId: 7, reactions: [], onToggle },
    });
    try {
      const button = Array.from(document.querySelectorAll<HTMLButtonElement>(".reaction-choice")).find(
        (choice) => choice.getAttribute("aria-label") === "React with 👀",
      );
      expect(button).not.toBeNull();
      button?.click();
      expect(onToggle).toHaveBeenCalledWith("👀");
    } finally {
      await unmount(component);
    }
  });

  it("keeps the touch picker open until a choice, outside tap, or Escape", async () => {
    const onToggle = vi.fn().mockResolvedValue(undefined);
    const component = mount(Reactions, {
      target: document.body,
      props: { messageId: 7, reactions: [], onToggle },
    });
    try {
      const add = document.querySelector<HTMLButtonElement>(".reaction-add");
      const picker = document.querySelector<HTMLElement>(".reaction-picker");
      expect(add).not.toBeNull();
      expect(picker).not.toBeNull();

      add?.click();
      await vi.waitFor(() => {
        expect(picker?.classList.contains("picker-open")).toBe(true);
      });

      document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
      await vi.waitFor(() => {
        expect(picker?.classList.contains("picker-open")).toBe(false);
      });

      add?.click();
      await vi.waitFor(() => {
        expect(picker?.classList.contains("picker-open")).toBe(true);
      });
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
      await vi.waitFor(() => {
        expect(picker?.classList.contains("picker-open")).toBe(false);
      });

      add?.click();
      const choice = document.querySelector<HTMLButtonElement>('[aria-label="React with ✅"]');
      choice?.click();
      await vi.waitFor(() => {
        expect(onToggle).toHaveBeenCalledWith("✅");
        expect(picker?.classList.contains("picker-open")).toBe(false);
      });
    } finally {
      await unmount(component);
    }
  });
});
