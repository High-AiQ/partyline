import { describe, expect, it } from "vitest";
import type { PresenceState, WorkingEvent } from "./contracts";
import {
  eventsAfterPresenceSnapshot,
  PresenceSnapshotBuffer,
  PresenceSnapshotSync,
  replacePresenceSnapshot,
  type PresenceSink,
} from "./presence-sync";

function state(id: string, phase: PresenceState["phase"], revision: number): PresenceState {
  return { id, phase, completion: "receipt", since: 1, turn: 1, revision };
}

function event(attachment_id: string, phase: WorkingEvent["phase"], revision: number): WorkingEvent {
  return {
    type: "working",
    attachment_id,
    working: phase === "working" || phase === "speaking",
    phase,
    completion: "receipt",
    since: 1,
    turn: 1,
    revision,
  };
}

describe("presence snapshot reconciliation", () => {
  it("replays a wire event newer than the REST snapshot", () => {
    expect(eventsAfterPresenceSnapshot([state("att", "working", 3)], [event("att", "speaking", 4)])).toEqual([
      event("att", "speaking", 4),
    ]);
  });

  it("drops wire events already represented by the snapshot", () => {
    expect(
      eventsAfterPresenceSnapshot(
        [state("att", "speaking", 4)],
        [event("att", "working", 3), event("att", "speaking", 4)],
      ),
    ).toEqual([]);
  });

  it("uses an idle tombstone to prevent stale working resurrection", () => {
    expect(eventsAfterPresenceSnapshot([state("att", "idle", 6)], [event("att", "working", 5)])).toEqual([]);
  });

  it("orders each attachment independently", () => {
    expect(
      eventsAfterPresenceSnapshot(
        [state("a", "idle", 6), state("b", "working", 2)],
        [event("a", "working", 5), event("b", "speaking", 3)],
      ),
    ).toEqual([event("b", "speaking", 3)]);
  });

  it("applies a structured snapshot, including its idle tombstone", () => {
    const calls: string[] = [];
    const sink: PresenceSink = {
      clear: () => calls.push("clear"),
      replaceLegacy: () => calls.push("legacy"),
      apply: (value) => calls.push(`${value.attachment_id}:${String(value.phase)}:${String(value.revision)}`),
    };

    replacePresenceSnapshot(sink, [state("active", "working", 2), state("done", "idle", 8)], ["legacy-att"]);

    expect(calls).toEqual(["clear", "active:working:2", "done:idle:8"]);
  });

  it("maps a quiet guess to legacy working false", () => {
    let applied: WorkingEvent | undefined;
    const sink: PresenceSink = {
      clear: () => undefined,
      replaceLegacy: () => undefined,
      apply: (value) => (applied = value),
    };

    replacePresenceSnapshot(sink, [state("att", "quiet", 4)], []);

    expect(applied).toMatchObject({ phase: "quiet", working: false, revision: 4 });
  });

  it("uses the boolean snapshot only when the structured field is absent", () => {
    const replacements: readonly string[][] = [];
    const sink: PresenceSink = {
      clear: () => undefined,
      replaceLegacy: (ids) => (replacements as string[][]).push([...ids]),
      apply: () => undefined,
    };

    replacePresenceSnapshot(sink, null, ["legacy-att"]);

    expect(replacements).toEqual([["legacy-att"]]);
  });
});

describe("presence fetch buffering", () => {
  it("replays a transition that arrives after the snapshot revision", () => {
    const buffer = new PresenceSnapshotBuffer();
    const fetch = buffer.begin();
    expect(buffer.capture(event("att", "speaking", 4))).toBe(true);

    expect(buffer.finish(fetch, [state("att", "working", 3)])).toEqual([event("att", "speaking", 4)]);
  });

  it("drops a buffered transition already represented by REST", () => {
    const buffer = new PresenceSnapshotBuffer();
    const fetch = buffer.begin();
    buffer.capture(event("att", "working", 3));

    expect(buffer.finish(fetch, [state("att", "idle", 4)])).toEqual([]);
  });

  it("carries events into a superseding resync and ignores the older result", () => {
    const buffer = new PresenceSnapshotBuffer();
    const older = buffer.begin();
    buffer.capture(event("att", "working", 2));
    const newer = buffer.begin();

    expect(buffer.finish(older, [state("att", "idle", 1)])).toBeNull();
    expect(buffer.finish(newer, [state("att", "idle", 1)])).toEqual([event("att", "working", 2)]);
  });

  it("returns buffered events when a resync fails", () => {
    const buffer = new PresenceSnapshotBuffer();
    const fetch = buffer.begin();
    buffer.capture(event("att", "speaking", 7));

    expect(buffer.abort(fetch)).toEqual([event("att", "speaking", 7)]);
    expect(buffer.capture(event("att", "idle", 8))).toBe(false);
  });
});

describe("presence snapshot coordinator", () => {
  it("buffers through fetch, installs REST, then replays the newer event", async () => {
    const calls: string[] = [];
    const sink: PresenceSink = {
      clear: () => calls.push("clear"),
      replaceLegacy: () => calls.push("legacy"),
      apply: (value) => calls.push(`${String(value.phase)}:${String(value.revision)}`),
    };
    const sync = new PresenceSnapshotSync(sink);
    const pending = sync.fetch(Promise.resolve("detail"));
    sync.apply(event("att", "speaking", 4));
    const [detail, fetch] = await pending;

    sync.finish(fetch, [state("att", "working", 3)], []);

    expect(detail).toBe("detail");
    expect(calls).toEqual(["clear", "working:3", "speaking:4"]);
  });

  it("replays held events when the REST request fails", async () => {
    const phases: string[] = [];
    const sink: PresenceSink = {
      clear: () => undefined,
      replaceLegacy: () => undefined,
      apply: (value) => phases.push(String(value.phase)),
    };
    const sync = new PresenceSnapshotSync(sink);
    const pending = sync.fetch(Promise.reject(new Error("offline")));
    sync.apply(event("att", "working", 2));

    await expect(pending).rejects.toThrow("offline");
    expect(phases).toEqual(["working"]);
  });
});
