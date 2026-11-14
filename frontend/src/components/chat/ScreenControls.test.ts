import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ScreenControls from "./ScreenControls.svelte";
import { screenApi } from "../../lib/screen-api";
import { ApiError } from "../../lib/http";
import { screenStatus } from "../../state/screen-status.svelte.js";
import { room } from "../../state/room.svelte.js";

/** Drains the promise chains a click starts; no clock involved. */
async function settle(): Promise<void> {
  for (let i = 0; i < 10; i++) await tick();
}

afterEach(() => {
  vi.restoreAllMocks();
  screenStatus.devices = [];
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

  it("does not fetch screen state on mount or when a push arrives", async () => {
    const interval = vi.spyOn(globalThis, "setInterval");
    const current = vi.spyOn(screenApi, "current");
    const devices = vi.spyOn(screenApi, "devices");
    const component = mount(ScreenControls, { target: document.body });
    screenStatus.devices = [];
    await tick();
    expect(current).not.toHaveBeenCalled();
    expect(devices).not.toHaveBeenCalled();
    expect(interval).not.toHaveBeenCalled();
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
    click("Pair this computer with Partyline");
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
    screenStatus.devices = devices;
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

describe("monitor preview failure", () => {
  const monitor = { id: 1, x: 0, y: 0, width: 3840, height: 2160, scale: 1, primary: true };
  const open = async () => {
    vi.spyOn(screenApi, "current").mockResolvedValue({ share: null });
    screenStatus.devices = [{ id: "d", name: "Desk", os: "Windows", online: true, monitors: [monitor] }];
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
    const press = (label: string) => {
      const button = [...document.querySelectorAll("button")].find((item) =>
        item.textContent.includes(label),
      );
      if (!button) throw new Error(`no button: ${label}`);
      button.click();
    };
    press("Desk (online)");
    await settle();
    return { component, press };
  };

  it("shows the server's reason, never a bare status, and still shares the full monitor", async () => {
    const reason = "Desk did not send a preview within 10 s; the helper may be busy or outdated";
    vi.spyOn(screenApi, "preview").mockRejectedValue(new ApiError(reason, 504));
    const start = vi.spyOn(screenApi, "start").mockResolvedValue({ share_id: "s", status: "waiting" });
    const { component, press } = await open();
    const note = document.querySelector("[data-testid=preview-unavailable]");
    expect(note?.textContent).toContain(`Preview unavailable: ${reason}`);
    expect(document.body.textContent).not.toContain("request failed");
    press("1 (3840 × 2160)");
    await settle();
    expect(document.body.textContent).toContain("The full monitor can still be shared");
    press("Share screen");
    await settle();
    expect(start).toHaveBeenCalledWith("line", "d", { x: 0, y: 0, width: 3840, height: 2160 }, false);
    await unmount(component);
  });

  it("keeps the other monitors' previews when one fails", async () => {
    vi.spyOn(screenApi, "preview").mockImplementation((_device, id) =>
      id === 1
        ? Promise.reject(new ApiError("Preview rate limit", 409))
        : Promise.resolve({ out_width: 1, out_height: 1, mime: "image/webp", data: "AAAA" }),
    );
    screenStatus.devices = [];
    vi.spyOn(screenApi, "current").mockResolvedValue({ share: null });
    screenStatus.devices = [
      {
        id: "d",
        name: "Desk",
        os: "Windows",
        online: true,
        monitors: [monitor, { ...monitor, id: 2 }],
      },
    ];
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
    [...document.querySelectorAll("button")].find((b) => b.textContent.includes("Desk (online)"))?.click();
    await settle();
    expect(document.querySelectorAll("[data-testid=preview-unavailable]")).toHaveLength(1);
    expect(document.querySelectorAll("button img")).toHaveLength(1);
    await unmount(component);
  });
});
