import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ScreenControls from "./ScreenControls.svelte";
import { screenApi } from "../../lib/screen-api";
import { screenStatus } from "../../state/screen-status.svelte.js";
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
    screenStatus.openPicker++;
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

describe("helper update notice", () => {
  const open = async (devices: Awaited<ReturnType<typeof screenApi.devices>>["devices"]) => {
    vi.spyOn(screenApi, "current").mockResolvedValue({ share: null });
    vi.spyOn(screenApi, "devices").mockResolvedValue({ devices });
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
    screenStatus.openPicker++;
    await settle();
    return component;
  };

  it("offers the download for an outdated Windows helper", async () => {
    const component = await open([
      {
        id: "d",
        name: "Desk",
        os: "Windows",
        online: true,
        monitors: [],
        helper_version: "2.80.0",
        update_available: true,
      },
    ]);
    const notice = document.querySelector("[data-testid=helper-update]");
    expect(notice?.textContent).toContain("Helper update available (running 2.80.0)");
    const link = document.querySelector<HTMLAnchorElement>("[data-testid=helper-update-download]");
    expect(link?.href).toContain("/releases/latest/download/PartylineHelper-Setup.exe");
    await unmount(component);
  });

  it("points other systems at the install command, and says nothing when the helper is current", async () => {
    const component = await open([
      {
        id: "a",
        name: "Mac",
        os: "Darwin",
        online: true,
        monitors: [],
        helper_version: "1",
        update_available: true,
      },
      {
        id: "b",
        name: "Fresh",
        os: "Windows",
        online: true,
        monitors: [],
        helper_version: "9",
        update_available: false,
      },
      { id: "c", name: "Old", os: "Windows", online: false, monitors: [] },
    ]);
    const notices = document.querySelectorAll("[data-testid=helper-update]");
    expect(notices).toHaveLength(1);
    expect(notices[0]?.textContent).toContain("install command");
    expect(document.querySelector("[data-testid=helper-update-download]")).toBeNull();
    await unmount(component);
  });
});
