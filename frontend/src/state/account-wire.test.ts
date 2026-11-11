import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import ComputersSection from "../components/settings/sections/ComputersSection.svelte";
import { connectAccountWire } from "./account-wire.svelte.js";
import { room } from "./room.svelte.js";
import { screenStatus } from "./screen-status.svelte.js";
import { wire } from "./wire.svelte.js";
import { WireEventSchema } from "../lib/events";

afterEach(() => {
  screenStatus.devices = [];
  screenStatus.indicators = [];
  vi.restoreAllMocks();
});

it("populates the home page and computer settings without an open line", async () => {
  room.conversation = null;
  const component = mount(ComputersSection, { target: document.body });
  const connect = vi.spyOn(wire, "connect").mockImplementation(() => undefined);
  connectAccountWire({ clientId: "tab" }, vi.fn());
  expect(connect.mock.calls[0]?.[0]).toBe("~account");
  const onEvent = connect.mock.calls[0]?.[2];
  if (!onEvent) throw new Error("missing account event handler");
  onEvent(
    WireEventSchema.parse({
      type: "screen_snapshot",
      devices: [{ id: "d", name: "Desk", os: "test", online: true, monitors: [] }],
      indicators: [{ conv_id: "line", device_name: "Desk", kind: "screen", label: "Desk screen share" }],
      share: null,
    }),
    { wasReady: true, claimRejected: false, rejectClaim: vi.fn() },
  );
  expect(screenStatus.devices[0]?.id).toBe("d");
  expect(screenStatus.indicators[0]?.conv_id).toBe("line");
  await tick();
  expect(document.body.textContent).toContain("Desk (online)");
  await unmount(component);
});
