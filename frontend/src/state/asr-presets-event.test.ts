import { afterEach, describe, expect, it, vi } from "vitest";
import { WireEventSchema } from "../lib/events";
import { onRoomWireEvent } from "./room-wire-events";
import type { RoomWireSink } from "./room-wire-events";
import { voicePresets } from "./voice-presets.svelte.js";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("asr_presets_changed", () => {
  it("is a valid wire frame and makes the mic refetch its recognizers", () => {
    const event = WireEventSchema.parse({ type: "asr_presets_changed" });
    const refresh = vi.spyOn(voicePresets, "refresh").mockImplementation(() => undefined);
    const room = { conversation: null } as unknown as RoomWireSink;
    onRoomWireEvent(room, event, { wasReady: true, claimRejected: false, rejectClaim: vi.fn() });
    expect(refresh).toHaveBeenCalledOnce();
  });
});
