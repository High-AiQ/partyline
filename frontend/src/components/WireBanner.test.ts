import { afterEach, describe, expect, it } from "vitest";
import { mount, unmount } from "svelte";
import WireBanner from "./WireBanner.svelte";
import { writeSet } from "../state/write-set.svelte.js";

describe("write-set notice banner", () => {
  afterEach(() => {
    writeSet.clear();
    document.body.innerHTML = "";
  });

  it("says a person decides and hides the review action for a human-only request", async () => {
    writeSet.request = {
      id: "request-1",
      conversation_id: "child",
      requester: "worker",
      path: "/repo/e2e/.seed",
      paths: ["/repo/e2e/.seed", "/repo/e2e/results"],
      human_only: true,
      already_granted: [],
      created_at: 1,
    };
    const component = mount(WireBanner, { target: document.body });
    await new Promise((done) => setTimeout(done, 0));
    const banner = document.querySelector("#writeSetRequest");
    expect(banner?.textContent).toContain("a person decides");
    expect(banner?.textContent).toContain("/repo/e2e/.seed, /repo/e2e/results");
    expect(banner?.querySelector("button")).toBeNull();
    void unmount(component);
  });
});
