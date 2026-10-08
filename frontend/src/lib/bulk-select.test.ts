import { describe, expect, it } from "vitest";
import { archiveOrder, toggleSelection } from "./bulk-select";

const lines = [
  { id: "root", parent_id: null },
  { id: "kid", parent_id: "root" },
  { id: "grandkid", parent_id: "kid" },
  { id: "solo", parent_id: null },
];

describe("bulk line selection", () => {
  it("selects a line with its whole subtree", () => {
    expect([...toggleSelection(new Set(), "kid", lines)].sort()).toEqual(["grandkid", "kid"]);
  });

  it("clearing a line clears its subtree and the ancestors that implied it", () => {
    const all = toggleSelection(toggleSelection(new Set(), "root", lines), "solo", lines);
    expect([...toggleSelection(all, "kid", lines)]).toEqual(["solo"]);
  });

  it("archives exactly the confirmed lines, deepest first", () => {
    expect(archiveOrder(new Set(["root", "kid", "grandkid", "solo"]), lines)).toEqual([
      "grandkid",
      "kid",
      "root",
      "solo",
    ]);
  });

  it("never adds a child line that was not confirmed", () => {
    expect(archiveOrder(new Set(["root"]), lines)).toEqual(["root"]);
  });

  it("does not loop on a malformed parent cycle", () => {
    const cycle = [
      { id: "a", parent_id: "b" },
      { id: "b", parent_id: "a" },
    ];
    expect(toggleSelection(new Set(["a", "b"]), "a", cycle).size).toBe(0);
  });
});
