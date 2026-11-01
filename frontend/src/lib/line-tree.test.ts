import { afterEach, describe, expect, it, vi } from "vitest";
import { lineTree, readExpandedLines, storeExpandedLines, LINE_TREE_STORAGE_KEY } from "./line-tree";

const lines = [
  { id: "root", live_count: 4 },
  { id: "child", parent_id: "root", live_count: 1 },
  { id: "grandchild", parent_id: "child", live_count: 2 },
  { id: "sibling", parent_id: "root", live_count: 0 },
  { id: "other", live_count: 0 },
];

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("line tree", () => {
  it("defaults to collapsed and counts every descendant and its live processes", () => {
    const rows = lineTree(lines, readExpandedLines());
    expect(rows.filter((row) => row.visible).map((row) => row.line.id)).toEqual(["root", "other"]);
    expect(rows[0]).toMatchObject({ descendants: 3, liveDescendants: 3, expanded: false });
    expect(rows[1]).toMatchObject({ descendants: 1, liveDescendants: 2 });
  });
  it("persists expanded lines and defaults new lines to collapsed", () => {
    storeExpandedLines(new Set(["root"]));
    expect(localStorage.getItem(LINE_TREE_STORAGE_KEY)).toBe('["root"]');
    expect(
      lineTree(lines, readExpandedLines())
        .filter((row) => row.visible)
        .map((row) => row.line.id),
    ).toEqual(["root", "child", "sibling", "other"]);
  });
  it("survives invalid and inaccessible storage", () => {
    localStorage.setItem(LINE_TREE_STORAGE_KEY, "{bad");
    expect(readExpandedLines().size).toBe(0);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error();
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error();
    });
    expect(readExpandedLines().size).toBe(0);
    expect(() => {
      storeExpandedLines(new Set(["root"]));
    }).not.toThrow();
  });
  it("expands all selected-line ancestors without changing saved choices", () => {
    const expanded = new Set<string>();
    const rows = lineTree(lines, expanded, "grandchild");
    expect(rows.filter((row) => row.visible).map((row) => row.line.id)).toEqual(lines.map((line) => line.id));
    expect(rows.slice(0, 2).every((row) => row.expanded)).toBe(true);
    expect(expanded.size).toBe(0);
  });
});
