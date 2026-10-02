import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import WireBanner from "./WireBanner.svelte";
import { fence } from "../state/fence.svelte";
import { memoryRequest } from "../state/memory-request.svelte.js";
import { memoryRequestApi } from "../lib/memory-request-api";
import { room } from "../state/room.svelte.js";

describe("wire banner preflight remedy", () => {
  afterEach(() => {
    fence.status = null;
    memoryRequest.clear();
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("keeps the person-side remedy visible while preflight is failing", () => {
    const remedy =
      "Person: create ~/.config/systemd/user/partyline.service.d/oom.conf with exactly:\n" +
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

  it("shows the memory request with one click approval and decline actions", async () => {
    memoryRequest.apply({
      id: "req-1",
      attachment_id: "worker",
      conv_id: "line",
      requester: "worker",
      requester_attachment_id: "worker",
      requested_limit: "6G",
      reason: "large test fixture",
      created_at: 1,
    });
    room.attachments = [
      {
        id: "worker",
        conv_id: "line",
        name: "worker",
        adapter: "fake",
        command: ["fake"],
        cwd: "/tmp",
        status: "running",
        last_seen: 0,
        created_at: 1,
        cli_session: null,
        cwd_git: null,
        memory_cap_bytes: 3 * 1024 ** 3,
      },
    ];
    const approve = vi.spyOn(memoryRequestApi, "approve").mockResolvedValue({ request: null });
    const component = mount(WireBanner, { target: document.body });
    try {
      const banner = document.querySelector("#memoryRequest");
      expect(banner?.textContent).toContain("3G → 6G");
      expect(banner?.textContent).toContain("large test fixture");
      expect(banner?.querySelector("span")?.classList.contains("whitespace-normal")).toBe(true);
      const button = banner?.querySelector<HTMLButtonElement>("button.primary");
      button?.click();
      await vi.waitFor(() => {
        expect(approve).toHaveBeenCalledWith("req-1");
      });
      await vi.waitFor(() => {
        expect(document.querySelector("#memoryRequest")).toBeNull();
      });
    } finally {
      await unmount(component);
    }
  });
});
