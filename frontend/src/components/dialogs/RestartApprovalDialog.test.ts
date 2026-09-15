import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import RestartApprovalDialog from "./RestartApprovalDialog.svelte";
import { api } from "../../lib/api";
import { restartApi } from "../../lib/restart-api";
import { restart } from "../../state/restart.svelte";
import { wire } from "../../state/wire.svelte";

describe("restart approval dialog", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    restart.request = null;
    document.body.innerHTML = "";
  });

  it("shows the fleet and approves the captain's request", async () => {
    restart.request = {
      id: "abc",
      conversation_id: "line",
      requester: "astra",
      reason: "1.19.1 merged and pulled",
      created_at: 1,
    };
    vi.spyOn(api, "running").mockResolvedValue([
      { name: "astra", adapter: "codex", conversation: "line" },
      { name: "luna", adapter: "codex", conversation: "kid" },
    ]);
    const approve = vi.spyOn(restartApi, "approve").mockResolvedValue({ request: null });
    const stopped = vi.spyOn(wire, "reportStopped").mockImplementation(() => undefined);
    const close = vi.fn();
    const dialog = mount(RestartApprovalDialog, { target: document.body, props: { close } });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("2 live processes");
      });
      expect(document.body.textContent).toContain("@astra");
      expect(document.body.textContent).toContain("1.19.1 merged and pulled");
      const button = [...document.querySelectorAll("button")].find((b) =>
        b.textContent.includes("approve restart"),
      );
      if (!button) throw new Error("no approve button");
      button.click();
      await vi.waitFor(() => {
        expect(approve).toHaveBeenCalledWith("abc");
      });
      await vi.waitFor(() => {
        expect(stopped).toHaveBeenCalled();
      });
      expect(restart.request).toBeNull();
    } finally {
      void unmount(dialog);
    }
  });
});
