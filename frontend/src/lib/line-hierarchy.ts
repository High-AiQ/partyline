/** Stable parent-first navigation without hiding orphans or malformed cycles. */
export interface ParentLinkedLine {
  id: string;
  parent_id?: string | null | undefined;
}

export interface LineRow<T> {
  line: T;
  depth: number;
}

export function orderedLines<T extends ParentLinkedLine>(lines: readonly T[]): LineRow<T>[] {
  const ids = new Set(lines.map((line) => line.id));
  const children = new Map<string, T[]>();
  for (const line of lines) {
    if (line.parent_id && ids.has(line.parent_id)) {
      const siblings = children.get(line.parent_id) ?? [];
      siblings.push(line);
      children.set(line.parent_id, siblings);
    }
  }
  const rows: LineRow<T>[] = [];
  const visited = new Set<string>();
  function visit(line: T, depth: number): void {
    if (visited.has(line.id)) return;
    visited.add(line.id);
    rows.push({ line, depth });
    for (const child of children.get(line.id) ?? []) visit(child, depth + 1);
  }
  for (const line of lines) {
    if (!line.parent_id || !ids.has(line.parent_id)) visit(line, 0);
  }
  // The server rejects cycles; still keep every line accessible after a bad response.
  for (const line of lines) visit(line, 0);
  return rows;
}

export function descendantLineIds(rootId: string, lines: readonly ParentLinkedLine[]): string[] {
  const ids = new Set(lines.map((line) => line.id));
  const children = new Map<string, string[]>();
  for (const line of lines) {
    if (line.parent_id && ids.has(line.parent_id)) {
      const siblings = children.get(line.parent_id) ?? [];
      siblings.push(line.id);
      children.set(line.parent_id, siblings);
    }
  }
  const result: string[] = [];
  const queue = [...(children.get(rootId) ?? [])];
  const seen = new Set(queue);
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) break;
    result.push(current);
    for (const child of children.get(current) ?? []) {
      if (!seen.has(child)) {
        seen.add(child);
        queue.push(child);
      }
    }
  }
  return result;
}
