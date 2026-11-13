import { z } from "zod";
import { orderedLines, type ParentLinkedLine } from "./line-hierarchy";

export const LINE_TREE_STORAGE_KEY = "partyline_expanded_lines";
const ExpandedLinesSchema = z.array(z.string());

export function readExpandedLines(): Set<string> {
  try {
    const parsed = ExpandedLinesSchema.safeParse(
      JSON.parse(localStorage.getItem(LINE_TREE_STORAGE_KEY) ?? "[]") as unknown,
    );
    return new Set(parsed.success ? parsed.data : []);
  } catch {
    return new Set();
  }
}

export function storeExpandedLines(expanded: ReadonlySet<string>): void {
  try {
    localStorage.setItem(LINE_TREE_STORAGE_KEY, JSON.stringify([...expanded]));
  } catch {
    // The in-memory choice still works if storage is unavailable.
  }
}

interface LiveLine extends ParentLinkedLine {
  live_count: number;
}

export interface TreeRow<T> {
  line: T;
  depth: number;
  descendants: number;
  liveDescendants: number;
  expanded: boolean;
  forced: boolean;
  visible: boolean;
}

/** Use the same cycle-safe ordering as the rail to calculate subtrees and visibility. */
export function lineTree<T extends LiveLine>(
  lines: readonly T[],
  expanded: ReadonlySet<string>,
  selectedId?: string,
  pinnedIds: ReadonlySet<string> = new Set(),
): TreeRow<T>[] {
  const ordered = orderedLines(lines);
  const forced = new Set<string>();
  const selectedIndex = ordered.findIndex((row) => row.line.id === selectedId);
  let selectedDepth = ordered[selectedIndex]?.depth ?? 0;
  for (let i = selectedIndex - 1; i >= 0 && selectedDepth > 0; i--) {
    const ancestor = ordered[i];
    if (ancestor && ancestor.depth < selectedDepth) {
      forced.add(ancestor.line.id);
      selectedDepth = ancestor.depth;
    }
  }
  for (const pinnedId of pinnedIds) {
    const pinnedIndex = ordered.findIndex((row) => row.line.id === pinnedId);
    let depth = ordered[pinnedIndex]?.depth ?? 0;
    for (let i = pinnedIndex - 1; i >= 0 && depth > 0; i--) {
      const ancestor = ordered[i];
      if (ancestor && ancestor.depth < depth) {
        forced.add(ancestor.line.id);
        depth = ancestor.depth;
      }
    }
  }
  return ordered.map(({ line, depth }, index) => {
    let end = index + 1;
    while (end < ordered.length && (ordered[end]?.depth ?? 0) > depth) end++;
    const descendants = ordered.slice(index + 1, end);
    let visible = true;
    for (let i = index - 1, childDepth = depth; i >= 0 && childDepth > 0; i--) {
      const ancestor = ordered[i];
      if (ancestor && ancestor.depth < childDepth) {
        if (!expanded.has(ancestor.line.id) && !forced.has(ancestor.line.id)) visible = false;
        childDepth = ancestor.depth;
      }
    }
    return {
      line,
      depth,
      descendants: descendants.length,
      liveDescendants: descendants.reduce((sum, row) => sum + row.line.live_count, 0),
      expanded: expanded.has(line.id) || forced.has(line.id),
      forced: forced.has(line.id),
      visible,
    };
  });
}

/** Keep each group in the rail's ordinary hierarchy order. */
export function starredFirst<T extends { line: { id: string } }>(
  rows: readonly T[],
  starredIds: ReadonlySet<string>,
): T[] {
  return [...rows].sort(
    (left, right) => Number(starredIds.has(right.line.id)) - Number(starredIds.has(left.line.id)),
  );
}
