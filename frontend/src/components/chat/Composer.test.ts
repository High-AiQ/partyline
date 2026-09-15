import { mount, unmount } from "svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import Composer from "./Composer.svelte";
import { layout } from "../../state/layout.svelte.js";

afterEach(() => {
  layout.narrow = false;
  document.body.replaceChildren();
});

describe("composer narrow layout", () => {
  it("uses the short placeholder and a one-line minimum on narrow screens", async () => {
    layout.narrow = true;
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      const input = document.querySelector<HTMLTextAreaElement>("#input");
      expect(input?.placeholder).toBe("say something…");
      expect(input?.classList.contains("min-h-7")).toBe(true);
    } finally {
      await unmount(component);
    }
  });

  it("keeps the addressing hint on desktop", async () => {
    layout.narrow = false;
    const component = mount(Composer, { target: document.body });
    try {
      await tick();
      expect(document.querySelector<HTMLTextAreaElement>("#input")?.placeholder).toBe(
        "say something… @name to ring an agent",
      );
    } finally {
      await unmount(component);
    }
  });
});
