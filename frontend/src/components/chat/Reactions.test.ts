import { mount, unmount } from "svelte";
import { describe, expect, it, vi } from "vitest";
import Reactions from "./Reactions.svelte";

describe("message reactions", () => {
  it("renders the picker and existing chips with accessible controls", async () => {
    const onToggle = vi.fn().mockResolvedValue(undefined);
    const component = mount(Reactions, {
      target: document.body,
      props: {
        messageId: 7,
        reactions: [{ emoji: "✅", reactors: ["greg", "sol"], mine: true }],
        onToggle,
      },
    });
    try {
      expect(document.querySelector('[aria-label="Reaction picker"]')).not.toBeNull();
      const choices = Array.from(document.querySelectorAll<HTMLButtonElement>(".reaction-choice"));
      expect(choices.some((button) => button.getAttribute("aria-label") === "React with 👍")).toBe(true);
      expect(document.querySelector('[aria-label*="Toggle ✅ reaction"]')?.textContent).toContain("2");
    } finally {
      await unmount(component);
    }
  });

  it("titles the trigger as react to this", async () => {
    const component = mount(Reactions, {
      target: document.body,
      props: { messageId: 7, reactions: [], onToggle: vi.fn().mockResolvedValue(undefined) },
    });
    try {
      const trigger = document.querySelector<HTMLButtonElement>(".reaction-add");
      expect(trigger?.getAttribute("title")).toBe("react to this");
      expect(trigger?.getAttribute("aria-label")).toBe("react to this");
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
