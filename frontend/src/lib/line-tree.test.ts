import { afterEach, describe, expect, it, vi } from "vitest";
import {
  lineTree,
  readExpandedLines,
  starredLineTree,
  storeExpandedLines,
  LINE_TREE_STORAGE_KEY,
  RAIL_GROUPS_STORAGE_KEY,
  readCollapsedGroups,
  storeCollapsedGroups,
} from "./line-tree";

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
  it("keeps a starred parent's expanded subtree inside the Starred group", () => {
    const rows = starredLineTree(lines, new Set(["root"]), undefined, new Set(["root"]));
    expect(rows.map((row) => [row.line.id, row.depth])).toEqual([
      ["root", 0],
      ["child", 1],
      ["grandchild", 2],
      ["sibling", 1],
    ]);
    expect(rows.filter((row) => row.visible).map((row) => row.line.id)).toEqual(["root", "child", "sibling"]);
  });
  it("puts a starred grandchild at depth zero without changing the main tree", () => {
    const expanded = new Set<string>();
    const starred = starredLineTree(lines, expanded, undefined, new Set(["grandchild"]));
    const main = lineTree(lines, expanded);
    expect(starred.map((row) => [row.line.id, row.depth])).toEqual([["grandchild", 0]]);
    expect(main.filter((row) => row.visible).map((row) => [row.line.id, row.depth])).toEqual([
      ["root", 0],
      ["other", 0],
    ]);
  });
  it("shows a nested star only inside its starred ancestor shortcut", () => {
    const rows = starredLineTree(
      lines,
      new Set(["root", "child"]),
      undefined,
      new Set(["root", "grandchild"]),
    );
    expect(rows.filter((row) => row.depth === 0).map((row) => row.line.id)).toEqual(["root"]);
    expect(rows.find((row) => row.line.id === "grandchild")?.depth).toBe(2);
  });
  it("does not let one sibling's collapsed subtree hide another sibling's descendants", () => {
    const siblings = [
      { id: "root", live_count: 0 },
      { id: "a", parent_id: "root", live_count: 0 },
      { id: "a-child", parent_id: "a", live_count: 0 },
      { id: "b", parent_id: "root", live_count: 0 },
      { id: "b-child", parent_id: "b", live_count: 0 },
    ];
    const rows = starredLineTree(siblings, new Set(["root", "b"]), undefined, new Set(["root"]));
    expect(rows.filter((row) => row.visible).map((row) => row.line.id)).toEqual([
      "root",
      "a",
      "b",
      "b-child",
    ]);
  });
  it("does not treat a starred sibling's descendant as nested beneath that star", () => {
    const siblings = [
      { id: "root", live_count: 0 },
      { id: "a", parent_id: "root", live_count: 0 },
      { id: "a-child", parent_id: "a", live_count: 0 },
      { id: "b", parent_id: "root", live_count: 0 },
      { id: "b-child", parent_id: "b", live_count: 0 },
    ];
    const rows = starredLineTree(siblings, new Set(), undefined, new Set(["a", "b-child"]));
    expect(rows.filter((row) => row.depth === 0).map((row) => row.line.id)).toEqual(["a", "b-child"]);
  });
  it("expands the selection path in both the shortcut and unchanged main tree", () => {
    const selected = "grandchild";
    const expanded = new Set<string>();
    const starred = starredLineTree(lines, expanded, selected, new Set(["root"]));
    const main = lineTree(lines, expanded, selected);
    expect(starred.filter((row) => row.visible).map((row) => row.line.id)).toEqual([
      "root",
      "child",
      "grandchild",
      "sibling",
    ]);
    expect(main.filter((row) => row.visible).map((row) => row.line.id)).toEqual(lines.map((line) => line.id));
  });
});

describe("collapsed rail groups", () => {
  it("defaults to both groups open and persists the collapsed ones", () => {
    expect([...readCollapsedGroups()]).toEqual([]);
    storeCollapsedGroups(new Set(["starred"]));
    expect([...readCollapsedGroups()]).toEqual(["starred"]);
    storeCollapsedGroups(new Set(["starred", "main"]));
    expect([...readCollapsedGroups()].sort()).toEqual(["main", "starred"]);
  });

  it("ignores corrupt or unknown stored values", () => {
    localStorage.setItem(RAIL_GROUPS_STORAGE_KEY, "not json");
    expect([...readCollapsedGroups()]).toEqual([]);
    localStorage.setItem(RAIL_GROUPS_STORAGE_KEY, JSON.stringify(["starred", "bogus"]));
    expect([...readCollapsedGroups()]).toEqual([]);
  });

  it("survives blocked storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect([...readCollapsedGroups()]).toEqual([]);
    expect(() => {
      storeCollapsedGroups(new Set(["main"]));
    }).not.toThrow();
  });
});
