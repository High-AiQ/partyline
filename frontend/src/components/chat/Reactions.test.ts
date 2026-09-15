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
});
