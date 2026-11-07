import { describe, expect, it } from "vitest";
import { controlBadge } from "./screen-control";
import { ScreenShareSchema, type ScreenShare } from "./screen-contracts";

function share(control: ScreenShare["control"]): ScreenShare {
  return {
    share_id: "s",
    handle: "alice",
    device_name: "DESKTOP-1",
    status: "active",
    region: { x: 0, y: 0, width: 10, height: 10 },
    control,
  };
}

describe("controlBadge", () => {
  it("names the computer and the action count for the holder", () => {
    const active = share({ status: "active", holder: "bob", actions: 12 });
    expect(controlBadge(active, "bob")?.label).toBe("Controlling DESKTOP-1 (12 actions)");
    expect(controlBadge(share({ status: "active", holder: "bob", actions: 1 }), "bob")?.label).toBe(
      "Controlling DESKTOP-1 (1 action)",
    );
  });

  it("says who holds control in the share status", () => {
    const active = share({ status: "active", holder: "bob", actions: 0 });
    expect(controlBadge(active)?.label).toBe("bob is controlling DESKTOP-1 (0 actions)");
    expect(controlBadge(share({ status: "active", holder: null, actions: 3 }))?.label).toBe(
      "Agents are controlling DESKTOP-1 (3 actions)",
    );
  });

  it("badges only the holder, never another process or a line-wide grant's process", () => {
    expect(controlBadge(share({ status: "active", holder: "bob", actions: 2 }), "carol")).toBeNull();
    expect(controlBadge(share({ status: "active", holder: null, actions: 2 }), "bob")).toBeNull();
  });

  it("disappears when control is pending, revoked, absent, or the share ends", () => {
    expect(controlBadge(share({ status: "pending", holder: "bob", actions: 0 }), "bob")).toBeNull();
    expect(controlBadge(share({ status: "revoked", holder: "bob", actions: 4 }), "bob")).toBeNull();
    expect(controlBadge(share(null))).toBeNull();
    expect(controlBadge(share(undefined))).toBeNull();
    expect(controlBadge(null, "bob")).toBeNull();
  });
});

describe("ScreenShareSchema control", () => {
  it("parses the server's control view and its absence", () => {
    const base = share(undefined);
    const withControl = {
      ...base,
      control: { status: "active", holder: null, requested_by: "alice", reason: "", actions: 2 },
    };
    expect(ScreenShareSchema.parse(withControl).control?.status).toBe("active");
    expect(ScreenShareSchema.parse({ ...base, control: null }).control).toBeNull();
    expect(ScreenShareSchema.parse(base).control).toBeUndefined();
  });
});
