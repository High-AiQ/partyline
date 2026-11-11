import { afterEach, expect, it, vi } from "vitest";
import { WireEventSchema } from "../lib/events";
import { onRoomWireEvent } from "./room-wire-events";
import { room } from "./room.svelte.js";
import { screenStatus } from "./screen-status.svelte.js";
import { screenApi } from "../lib/screen-api";

afterEach(() => {
  screenStatus.indicators = [];
  screenStatus.devices = [];
  room.screenShare = null;
  vi.restoreAllMocks();
});

it("applies a socket snapshot without fetching screen state", () => {
  const indicators = vi.spyOn(screenApi, "indicators");
  const devices = vi.spyOn(screenApi, "devices");
  const current = vi.spyOn(screenApi, "current");
  const event = WireEventSchema.parse({
    type: "screen_snapshot",
    indicators: [{ conv_id: "line", device_name: "Desk", kind: "screen", label: "Desk screen share" }],
    devices: [{ id: "d", name: "Desk", os: "test", online: true, monitors: [] }],
    share: {
      share_id: "s",
      handle: "alice",
      device_name: "Desk",
      status: "active",
      region: { x: 0, y: 0, width: 1, height: 1 },
    },
  });
  onRoomWireEvent(room, event, { wasReady: true, claimRejected: false, rejectClaim: vi.fn() });
  expect(screenStatus.indicators[0]?.conv_id).toBe("line");
  expect(screenStatus.devices[0]?.id).toBe("d");
  expect(room.screenShare?.share_id).toBe("s");
  expect(indicators).not.toHaveBeenCalled();
  expect(devices).not.toHaveBeenCalled();
  expect(current).not.toHaveBeenCalled();
});
