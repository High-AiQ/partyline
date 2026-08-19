import { mount, unmount } from "svelte";
import { describe, expect, it } from "vitest";
import InstanceBanner from "./InstanceBanner.svelte";

describe("InstanceBanner", () => {
  it("names the configured instance in visible and accessible text", async () => {
    const banner = mount(InstanceBanner, {
      target: document.body,
      props: { name: "Cockpit" },
    });
    try {
      const status = document.querySelector('[role="status"]');
      expect(status?.textContent).toContain("Cockpit");
      expect(status?.getAttribute("aria-label")).toBe("Partyline instance: Cockpit");
    } finally {
      await unmount(banner);
    }
  });
});
