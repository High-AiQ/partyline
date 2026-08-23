import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import type { Attachment } from "../../lib/contracts";
import { room } from "../../state/room.svelte.js";
import FollowToggle from "./FollowToggle.svelte";

const attachment: Attachment = {
  id: "att-lead",
  conv_id: "line",
  name: "grok",
  adapter: "grok",
  command: ["grok"],
  cwd: "/tmp/work",
  status: "running",
  follow: false,
  last_seen: 1,
  created_at: 1,
  cli_session: null,
  cwd_git: null,
};

afterEach(() => {
  room.attachments = [];
  vi.restoreAllMocks();
});

describe("FollowToggle", () => {
  it("asks the server to make this jack the lead follower", async () => {
    const update = vi.spyOn(api, "setAttachmentFollow").mockResolvedValue({
      ...attachment,
      follow: true,
    });
    const component = mount(FollowToggle, {
      target: document.body,
      props: { attachment },
    });
    try {
      const button = document.querySelector<HTMLButtonElement>("button.follow");
      expect(button?.getAttribute("aria-pressed")).toBe("false");
      button?.click();
      await vi.waitFor(() => {
        expect(update).toHaveBeenCalledWith("att-lead", { follow: true });
        expect(room.attachments[0]?.follow).toBe(true);
      });
    } finally {
      await unmount(component);
    }
  });
});
