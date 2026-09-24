import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import WireBanner from "./WireBanner.svelte";
import { fence } from "../state/fence.svelte";

describe("wire banner fence remedy", () => {
  afterEach(() => {
    fence.status = null;
    document.body.innerHTML = "";
  });

  it("keeps the person-side remedy visible while preflight is failing", () => {
    fence.status = {
      ok: false,
      backend: "bubblewrap",
      platform: "linux",
      reason: "user namespaces are disabled",
      remedy: "apt-get install -y bubblewrap",
    };
    const component = mount(WireBanner, { target: document.body });
    try {
      expect(document.querySelector("#fenceUnavailable")?.textContent).toContain(
        "apt-get install -y bubblewrap",
      );
    } finally {
      void unmount(component);
    }
  });
});
