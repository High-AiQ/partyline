import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it } from "vitest";
import ChromeApprovalNotice from "./ChromeApprovalNotice.svelte";
import { WireEventSchema } from "../lib/events";
import { onRoomWireEvent } from "../state/room-wire-events";
import { chromeApproval } from "../state/chrome-approval.svelte.js";
import { room } from "../state/room.svelte.js";

const context = { wasReady: true, claimRejected: false, rejectClaim: () => undefined };

function push(conv: string, titles: string[]): void {
  onRoomWireEvent(
    room,
    WireEventSchema.parse({
      type: "chrome_approval",
      conv_id: conv,
      notices: titles.map((title, index) => ({ grant_id: `g${String(index)}`, title, device_name: "Desk" })),
    }),
    context,
  );
}

afterEach(() => {
  chromeApproval.reset();
  room.conversation = null;
  document.body.replaceChildren();
});

function open() {
  room.conversation = { id: "line" } as typeof room.conversation;
  return mount(ChromeApprovalNotice, { target: document.body });
}

it("tells the person where Chrome waits for Allow, then clears when it no longer does", async () => {
  const component = open();
  expect(document.querySelector("#chromeApproval")).toBeNull();
  push("line", ["Shared page"]);
  await tick();
  const notice = document.querySelector("#chromeApproval");
  expect(notice?.getAttribute("role")).toBe("status");
  expect(notice?.textContent).toContain(
    "Chrome is waiting for you to click Allow in the shared window (Shared page)",
  );
  push("line", []); // approved, refused or the share ended
  await tick();
  expect(document.querySelector("#chromeApproval")).toBeNull();
  await unmount(component);
});

it("shows only the open line's windows", async () => {
  const component = open();
  push("elsewhere", ["Other page"]);
  await tick();
  expect(document.querySelector("#chromeApproval")).toBeNull();
  push("line", ["One", "Two"]);
  await tick();
  expect(document.querySelectorAll("#chromeApproval span")).toHaveLength(2);
  await unmount(component);
});

it("forgets what it was told when the wire reconnects", async () => {
  const component = open();
  push("line", ["Shared page"]);
  chromeApproval.reset();
  await tick();
  expect(document.querySelector("#chromeApproval")).toBeNull();
  await unmount(component);
});
