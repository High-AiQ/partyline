import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import WireBanner from "./WireBanner.svelte";
import { fence } from "../state/fence.svelte";

describe("wire banner preflight remedy", () => {
  afterEach(() => {
    fence.status = null;
    document.body.innerHTML = "";
  });

  it("keeps the person-side remedy visible while preflight is failing", () => {
    const remedy =
      "Person: create ~/.config/systemd/user/partyline-lan.service.d/oom.conf with exactly:\n" +
      "[Service]\nOOMPolicy=continue\nMemoryMax=40G\n" +
      "Then run: systemctl --user daemon-reload\n" +
      "After reload, file a Partyline restart request and have a person approve it.";
    fence.status = {
      ok: false,
      backend: "bubblewrap",
      platform: "linux",
      reason: "the Partyline unit memory guard is missing",
      remedy,
    };
    const component = mount(WireBanner, { target: document.body });
    try {
      const banner = document.querySelector("#fenceUnavailable");
      expect(banner?.querySelector("strong")?.textContent).toContain("Partyline preflight failed");
      const remedyText = banner?.querySelector("pre");
      expect(remedyText?.textContent).toBe(`Remedy: ${remedy}`);
      expect(remedyText?.classList.contains("whitespace-pre-wrap")).toBe(true);
    } finally {
      void unmount(component);
    }
  });
});
