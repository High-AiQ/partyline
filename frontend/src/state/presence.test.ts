import { afterEach, describe, expect, it } from "vitest";
import { presence } from "./presence.svelte.js";
import type { PresenceState, WorkingEvent } from "../lib/contracts";

function event(overrides: Partial<WorkingEvent> = {}): WorkingEvent {
  return {
    type: "working",
    attachment_id: "att",
    working: true,
    phase: "working",
    completion: "receipt",
    since: 1_000_000,
    turn: 1,
    revision: 1,
    held: 0,
    ...overrides,
  };
}

function state(overrides: Partial<PresenceState> = {}): PresenceState {
  return {
    id: "att",
    phase: "working",
    completion: "receipt",
    since: 1_000_000,
    turn: 1,
    revision: 1,
    held: 0,
    ...overrides,
  };
}

afterEach(() => {
  presence.clear();
});

describe("presence store", () => {
  it("records a modern announce with its revision", () => {
    presence.apply(event());
    expect(presence.entries.get("att")).toMatchObject({ phase: "working", revision: 1, legacy: false });
  });

  it("ignores a strictly older announce, the late-delivery downgrade", () => {
    presence.apply(event({ phase: "speaking", revision: 4 }));
    presence.apply(event({ phase: "idle", revision: 3 }));
    expect(presence.entries.get("att")).toMatchObject({ phase: "speaking", revision: 4 });
  });

  it("passes equal revisions through: legacy frames carry no ordering", () => {
    presence.apply({ type: "working", attachment_id: "att", working: true });
    presence.apply({ type: "working", attachment_id: "att", working: false });
    expect(presence.entries.get("att")).toMatchObject({ phase: "idle", legacy: true });
  });

  it("keeps idle tombstones so a stale event cannot resurrect a badge", () => {
    presence.apply(event({ phase: "idle", revision: 9 }));
    presence.apply(event({ phase: "working", revision: 8 }));
    expect(presence.entries.get("att")).toMatchObject({ phase: "idle", revision: 9 });
  });

  it("adopts a structured snapshot atomically, tombstones included", () => {
    presence.apply(event({ phase: "working", revision: 2 }));
    presence.replace([
      state({ id: "a", phase: "working", revision: 5 }),
      state({ id: "b", phase: "idle", revision: 8 }),
    ]);
    expect([...presence.entries.keys()].sort()).toEqual(["a", "b"]);
    expect(presence.entries.get("b")).toMatchObject({ phase: "idle", revision: 8 });
  });

  it("adopts a legacy boolean snapshot as busy entries that never decay", () => {
    presence.replaceLegacy(["att"]);
    expect(presence.entries.get("att")).toMatchObject({ phase: "working", legacy: true });
  });
});

describe("receipt capability end to end", () => {
  // The manifest's turn_end never reaches the browser: the server republishes
  // it as `completion` on the presence wire. This is the chain a
  // turn_end = "receipt" adapter rides.
  it("applies a receipt-completion announce and renders its treatment", async () => {
    presence.apply(event({ phase: "working", completion: "receipt", revision: 3 }));
    const entry = presence.entries.get("att");
    expect(entry).toMatchObject({ phase: "working", completion: "receipt" });
    const { badgeTreatment } = await import("../lib/presence-badge.js");
    expect(badgeTreatment(entry, entry?.since ?? 0)).toMatchObject({
      label: "working…",
      dot: "filled",
      pulse: "live",
    });
  });
});
