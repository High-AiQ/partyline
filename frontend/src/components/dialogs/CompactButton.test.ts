import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import CompactButton from "./CompactButton.svelte";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

describe("CompactButton", () => {
  it("reports a mid-turn request as queued", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true, queued: true }),
    });
    vi.stubGlobal("fetch", fetch);
    const button = mount(CompactButton, {
      target: document.body,
      props: { attachmentId: "att-1" },
    });
    try {
      document.querySelector<HTMLButtonElement>("button")?.click();
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("queued for turn end");
      });
      await tick();
      expect(fetch).toHaveBeenCalledWith("/api/attachments/att-1/compact", { method: "POST" });
    } finally {
      await unmount(button);
    }
  });
});
