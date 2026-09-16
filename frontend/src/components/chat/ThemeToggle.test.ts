import { mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import ThemeToggle from "./ThemeToggle.svelte";
import { theme } from "../../state/theme.svelte.js";

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  document.body.replaceChildren();
});

describe("ThemeToggle", () => {
  it("keeps a stable accessible name across state and only flips aria-pressed", async () => {
    theme.set("light");
    const app = mount(ThemeToggle, { target: document.body });
    try {
      const button = document.querySelector("button");
      if (!button) throw new Error("missing toggle button");
      expect(button.getAttribute("aria-label")).toBe("dark theme");
      expect(button.getAttribute("aria-pressed")).toBe("false");

      button.click();
      await tick();
      expect(button.getAttribute("aria-label")).toBe("dark theme");
      expect(button.getAttribute("aria-pressed")).toBe("true");

      button.click();
      await tick();
      expect(button.getAttribute("aria-label")).toBe("dark theme");
      expect(button.getAttribute("aria-pressed")).toBe("false");
    } finally {
      await unmount(app);
    }
  });
});
