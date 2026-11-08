import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import ControlBadge from "./ControlBadge.svelte";
import ScreenControls from "./ScreenControls.svelte";
import { layout } from "../../state/layout.svelte.js";
import { room } from "../../state/room.svelte.js";
import { screenApi } from "../../lib/screen-api";
import type { ScreenShare } from "../../lib/screen-contracts";
import { vi } from "vitest";

const line = { id: "line", name: "Line", topic: "", created_at: 1, archived_at: null, live_count: 0 };
const base: ScreenShare = {
  share_id: "s",
  handle: "alice",
  device_name: "DESKTOP-9",
  status: "active",
  region: { x: 0, y: 0, width: 100, height: 100 },
};

afterEach(() => {
  vi.restoreAllMocks();
  layout.narrow = false;
  room.screenShare = null;
  room.leave({ clearRoute: false });
  document.body.replaceChildren();
});

describe("control badge", () => {
  it("appears for the holder with the computer and count, and follows live events", async () => {
    room.screenShare = { ...base, control: { status: "active", holder: "bob", actions: 7 } };
    const mine = mount(ControlBadge, { target: document.body, props: { handle: "bob" } });
    const other = mount(ControlBadge, { target: document.body, props: { handle: "carol" } });
    await tick();
    const badges = document.querySelectorAll(".control-badge");
    expect(badges).toHaveLength(1);
    expect(badges[0]?.getAttribute("aria-label")).toBe("Controlling DESKTOP-9 (7 actions)");
    expect(badges[0]?.querySelector("svg")).not.toBeNull();
    expect(badges[0]?.querySelector(".control-dot")).not.toBeNull();

    room.screenShare = { ...base, control: { status: "active", holder: "bob", actions: 8 } };
    await tick();
    expect(document.querySelector(".control-badge")?.getAttribute("aria-label")).toContain("(8 actions)");

    room.screenShare = { ...base, control: { status: "revoked", holder: "bob", actions: 8 } };
    await tick();
    expect(document.querySelector(".control-badge")).toBeNull();

    room.screenShare = { ...base, control: { status: "active", holder: "bob", actions: 9 } };
    await tick();
    expect(document.querySelector(".control-badge")).not.toBeNull();
    room.screenShare = null;
    await tick();
    expect(document.querySelector(".control-badge")).toBeNull();
    await unmount(mine);
    await unmount(other);
  });

  it("turns the pulse off for reduced motion and uses theme tokens for colour", async () => {
    const source = await import("./ControlBadge.svelte?raw");
    const text = source.default;
    expect(text).toMatch(/prefers-reduced-motion: reduce\)\s*{\s*\.control-dot\s*{\s*animation: none/);
    expect(text).toContain("text-pink");
    expect(text).not.toMatch(/#[0-9a-f]{6}/i);
  });
});

describe("share status", () => {
  it("shows who is in control beside the share and drops it on revoke", async () => {
    vi.spyOn(screenApi, "current").mockResolvedValue({ share: null });
    room.conversation = line;
    const component = mount(ScreenControls, { target: document.body });
    await tick();
    room.screenShare = { ...base, control: { status: "active", holder: null, actions: 0 } };
    await tick();
    expect(document.querySelector(".control-badge")?.getAttribute("aria-label")).toBe(
      "Agents are controlling DESKTOP-9 (0 actions)",
    );
    room.screenShare = { ...base, control: { status: "pending", holder: "bob", actions: 0 } };
    await tick();
    expect(document.querySelector(".control-badge")).toBeNull();
    await unmount(component);
  });

  it("hides Computers / Share screen on a phone but keeps a running share and its Stop", async () => {
    vi.spyOn(screenApi, "current").mockResolvedValue({ share: null });
    const stop = vi.spyOn(screenApi, "stop").mockResolvedValue({ ok: true } as never);
    layout.narrow = true;
    room.conversation = line;
    room.screenShare = null;
    const component = mount(ScreenControls, { target: document.body });
    await tick();
    expect(document.body.textContent).not.toContain("Computers / Share screen");
    expect(document.body.textContent.trim()).toBe("");

    room.screenShare = { ...base, control: { status: "active", holder: "bob", actions: 3 } };
    await tick();
    const buttons = [...document.querySelectorAll("button")];
    expect(buttons.map((b) => b.textContent)).toEqual(["Stop"]);
    expect(document.body.textContent).toContain("alice is sharing DESKTOP-9");
    expect(document.querySelector(".control-badge")).not.toBeNull();
    buttons[0]?.click();
    expect(stop).toHaveBeenCalledWith("s");

    layout.narrow = false;
    await tick();
    expect(document.body.textContent).not.toContain("Computers / Share screen");
    await unmount(component);
  });
});
