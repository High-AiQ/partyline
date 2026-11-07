import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ScreenControls from "./ScreenControls.svelte";
import { screenApi } from "../../lib/screen-api";
import { room } from "../../state/room.svelte.js";

afterEach(() => {
  vi.restoreAllMocks();
  room.leave({ clearRoute: false });
  document.body.replaceChildren();
});

describe("screen consent", () => {
  it("shows the helper's prompt-pending decline reason", async () => {
    vi.spyOn(screenApi, "current").mockResolvedValue({ share: null });
    room.conversation = {
      id: "line",
      name: "Line",
      topic: "",
      created_at: 1,
      archived_at: null,
      live_count: 0,
    };
    const component = mount(ScreenControls, { target: document.body });
    try {
      await tick();
      room.screenShare = {
        share_id: "s",
        handle: "alice",
        device_name: "Desk",
        status: "declined",
        reason: "prompt pending",
        region: { x: -100, y: 0, width: 100, height: 100 },
      };
      await tick();
      expect(document.body.textContent).toContain("Sharing declined: prompt pending");
    } finally {
      await unmount(component);
    }
  });
});
