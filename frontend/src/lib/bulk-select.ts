/**
 * Selection rules for archiving many lines at once.
 *
 * An archived parent cannot hold a live child, so selecting a line selects its
 * whole subtree, and clearing a line clears every ancestor that implied it.
 * The archive order then takes the deepest lines first, so the server never
 * sees a parent before its own descendants.
 */
import { descendantLineIds, type ParentLinkedLine } from "./line-hierarchy";

function ancestorIds(id: string, lines: readonly ParentLinkedLine[]): string[] {
  const parents = new Map(lines.map((line) => [line.id, line.parent_id ?? null]));
  const found: string[] = [];
  let current = parents.get(id) ?? null;
  while (current && parents.has(current) && !found.includes(current)) {
    found.push(current);
    current = parents.get(current) ?? null;
  }
  return found;
}

export function toggleSelection(
  selected: ReadonlySet<string>,
  id: string,
  lines: readonly ParentLinkedLine[],
): Set<string> {
  const next = new Set(selected);
  const subtree = [id, ...descendantLineIds(id, lines)];
  if (selected.has(id)) {
    for (const each of [...subtree, ...ancestorIds(id, lines)]) next.delete(each);
  } else {
    for (const each of subtree) next.add(each);
  }
  return next;
}

/**
 * Archive order for exactly the confirmed lines: deepest first, one at a time,
 * never with `include_children`. A child line created after confirmation is
 * therefore never swept up — the server refuses its parent instead.
 */
export function archiveOrder(selected: ReadonlySet<string>, lines: readonly ParentLinkedLine[]): string[] {
  const depth = (id: string) => ancestorIds(id, lines).length;
  return [...selected].sort((a, b) => depth(b) - depth(a));
}
