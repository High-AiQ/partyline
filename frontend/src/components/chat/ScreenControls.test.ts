import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ScreenControls from "./ScreenControls.svelte";
import { screenApi } from "../../lib/screen-api";
import { room } from "../../state/room.svelte.js";

/** Drains the promise chains a click starts; no clock involved. */
async function settle(): Promise<void> {
  for (let i = 0; i < 10; i++) await tick();
}

afterEach(() => {
  vi.restoreAllMocks();
  room.leave({ clearRoute: false });
  document.body.replaceChildren();
});

describe("screen consent", () => {
  it("shows the recording indicator to everyone viewing the line", async () => {
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
    await tick();
    room.screenShare = {
      share_id: "s",
      handle: "alice",
      device_name: "Desk",
      status: "active",
      region: { x: 0, y: 0, width: 100, height: 100 },
      walkthrough: true,
      recording: true,
    };
    await tick();
    expect(document.body.textContent).toContain("alice is recording a walkthrough on Desk");
    const row = [...document.querySelectorAll("div")].find((item) =>
      item.textContent.includes("alice is recording a walkthrough on Desk"),
    );
    expect(row?.classList.contains("flex-none")).toBe(true);
    await unmount(component);
  });

  it("keeps a newer share event when the initial status response arrives late", async () => {
    let respond: ((result: Awaited<ReturnType<typeof screenApi.current>>) => void) | undefined;
    vi.spyOn(screenApi, "current").mockImplementation(
      () =>
        new Promise((resolve) => {
          respond = resolve;
        }),
    );
    room.conversation = {
      id: "line",
      name: "Line",
      topic: "",
      created_at: 1,
      archived_at: null,
      live_count: 0,
    };
    room.screenShare = null;
    const component = mount(ScreenControls, { target: document.body });
    await tick();
    room.screenShare = {
      share_id: "s",
      handle: "alice",
      device_name: "Desk",
      status: "active",
      region: { x: 0, y: 0, width: 100, height: 100 },
    };
    respond?.({ share: null });
    await tick();
    expect(room.screenShare.share_id).toBe("s");
    await unmount(component);
  });

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

describe("pairing instructions", () => {
  it("shows the expiry and where to run the commands once a code exists", async () => {
    vi.spyOn(screenApi, "current").mockResolvedValue({ share: null });
    vi.spyOn(screenApi, "devices").mockResolvedValue({ devices: [] });
    vi.spyOn(screenApi, "pair").mockResolvedValue({ code: "XYZ-789" } as Awaited<
      ReturnType<typeof screenApi.pair>
    >);
    room.conversation = {
      id: "line",
      name: "Line",
      topic: "",
      created_at: 1,
      archived_at: null,
      live_count: 0,
    };
    const component = mount(ScreenControls, { target: document.body });
    await tick();
    const click = (label: string): void => {
      const button = [...document.querySelectorAll("button")].find(
        (item) => item.textContent.trim() === label,
      );
      if (!button) throw new Error(`missing ${label}`);
      button.click();
    };
    click("Computers / Share screen");
    await tick();
    click("Pair a computer");
    await settle();
    expect(document.body.textContent).toContain("XYZ-789");

    const text = document.body.textContent.replace(/\s+/g, " ");
    expect(text).toContain("expires in 5 minutes");
    expect(text).toContain("not on the Partyline server");
    expect(text).toContain(`partyline-helper pair ${window.location.origin} XYZ-789`);
    await unmount(component);
  });
});
