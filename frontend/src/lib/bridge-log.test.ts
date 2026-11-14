import { describe, expect, it } from "vitest";
import type { Bridge, BridgeLogEntry } from "./bridge-api";
import { arrangeLog, logSides, monogram, speakerLineId, stripBridgeAddress } from "./bridge-log";

const bridge: Bridge = {
  id: "b",
  opened_at: 1_700_000_000,
  opened_by: "greg",
  sides: [
    { conv_id: "x", conv_name: "storytime", attachment_id: "xa", name: "opus" },
    { conv_id: "y", conv_name: "partyline dev", attachment_id: "ya", name: "opus" },
  ],
};
const entry = (id: number, conv: string, at: number, source?: string): BridgeLogEntry => ({
  id,
  conv_id: conv,
  sender: "opus",
  body: `m${String(id)}`,
  created_at: at,
  source_conv_id: source ?? null,
});
const DAY = 86_400;

describe("stripBridgeAddress", () => {
  it("drops only the leading address", () => {
    expect(stripBridgeAddress("@[bridge]opus I'm reporting")).toBe("I'm reporting");
    expect(stripBridgeAddress("  @[bridge]Fable: hello @[bridge]fable")).toBe("hello @[bridge]fable");
    expect(stripBridgeAddress("@[bridge]opus\n\n1. first")).toBe("1. first");
    expect(stripBridgeAddress("no address here")).toBe("no address here");
  });
});

describe("sides", () => {
  it("puts the open line first with an outgoing arrow, whichever side it is", () => {
    const [own, other] = logSides(bridge, "y");
    expect([own.side.conv_name, own.mine, own.arrow]).toEqual(["partyline dev", true, "→"]);
    expect([other.side.conv_name, other.mine, other.arrow]).toEqual(["storytime", false, "←"]);
    expect(logSides(bridge, "x")[0].side.conv_id).toBe("x");
  });

  it("names the speaker by the source line of a copy and by the line of an original", () => {
    expect(speakerLineId(entry(1, "x", 1))).toBe("x");
    expect(speakerLineId(entry(2, "y", 1, "x"))).toBe("x");
  });

  it("makes a monogram from the line name", () => {
    expect(monogram("more a plus content")).toBe("MA");
    expect(monogram("tool")).toBe("TO");
    expect(monogram("«3d game»")).toBe("3G");
    expect(monogram("")).toBe("?");
  });
});

describe("arrangeLog", () => {
  const sides = logSides(bridge, "x");
  const now = new Date(1_700_000_000_000);

  it("groups a side's consecutive messages and splits where the speaker changes", () => {
    const items = arrangeLog(
      [entry(1, "x", 1_700_000_000), entry(2, "x", 1_700_000_060), entry(3, "y", 1_700_000_120)],
      sides,
      now,
    );
    expect(items.map((i) => i.kind)).toEqual(["day", "group", "group"]);
    const groups = items.filter((i) => i.kind === "group");
    expect(groups.map((g) => g.entries.map((e) => e.id))).toEqual([[1, 2], [3]]);
    expect(groups.map((g) => g.speaker.mine)).toEqual([true, false]);
  });

  it("starts a new run after a long pause and a new day with a divider", () => {
    const items = arrangeLog(
      [entry(1, "x", 1_700_000_000), entry(2, "x", 1_700_001_000), entry(3, "x", 1_700_000_000 + 2 * DAY)],
      sides,
      now,
    );
    expect(items.map((i) => i.kind)).toEqual(["day", "group", "group", "day", "group"]);
    const labels = items.filter((i) => i.kind === "day").map((i) => i.label);
    expect(labels[0]).toBe("Today");
    expect(labels).toHaveLength(2);
  });

  it("orders by time then id and tolerates a line it does not know", () => {
    const items = arrangeLog([entry(2, "x", 20), entry(1, "y", 10), entry(3, "elsewhere", 30)], sides, now);
    const groups = items.filter((i) => i.kind === "group");
    expect(groups.map((g) => g.entries[0]?.id)).toEqual([1, 2, 3]);
    expect(groups[2]?.speaker.mine).toBe(false);
  });

  it("is empty for an empty log", () => {
    expect(arrangeLog([], sides, now)).toEqual([]);
  });
});
