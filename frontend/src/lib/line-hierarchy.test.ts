import { describe, expect, it } from "vitest";
import { orderedLines } from "./line-hierarchy";

describe("line hierarchy navigation", () => {
  it("keeps children beside their parent even when creation order is reversed", () => {
    const rows = orderedLines([
      { id: "new child", parent_id: "project" },
      { id: "other" },
      { id: "old child", parent_id: "project" },
      { id: "project" },
    ]);
    expect(rows.map(({ line, depth }) => [line.id, depth])).toEqual([
      ["other", 0],
      ["project", 0],
      ["new child", 1],
      ["old child", 1],
    ]);
  });

  it("keeps orphaned lines and cycles reachable once each", () => {
    const lines = [
      { id: "orphan", parent_id: "archived" },
      { id: "a", parent_id: "b" },
      { id: "b", parent_id: "a" },
    ];
    expect(orderedLines(lines).map(({ line }) => line.id)).toEqual(["orphan", "a", "b"]);
  });
});
