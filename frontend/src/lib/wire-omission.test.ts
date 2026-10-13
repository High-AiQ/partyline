import { describe, expect, it } from "vitest";
import type { z } from "zod";
import { ResourcesEventSchema, WireEventSchema } from "./events";

// The server's broadcast() and handshake drop None fields (`exclude_none=True`), so a
// field that can be null must also parse when it is missing.
type Node = z.ZodType;
interface Def {
  type: string;
  shape?: Record<string, Node>;
  options?: Node[];
  element?: Node;
  innerType?: Node;
  out?: Node;
  getter?: () => Node;
}

function def(schema: Node): Def {
  return (schema as unknown as { _zod: { def: Def } })._zod.def;
}

/** Paths of fields that accept null but reject a missing value. */
function nullOnly(schema: Node, path: string, seen: Set<Node>, found: string[]): void {
  if (seen.has(schema)) return;
  seen.add(schema);
  const d = def(schema);
  if (d.type === "object" && d.shape) {
    for (const [key, field] of Object.entries(d.shape)) {
      const at = `${path}.${key}`;
      if (field.safeParse(null).success && !field.safeParse(undefined).success) found.push(at);
      nullOnly(field, at, seen, found);
    }
  } else if (d.type === "union") {
    d.options?.forEach((option) => {
      nullOnly(option, path, seen, found);
    });
  } else if (d.type === "array" && d.element) {
    nullOnly(d.element, `${path}[]`, seen, found);
  } else if (d.type === "pipe" && d.out) {
    nullOnly(d.out, path, seen, found);
  } else if (d.type === "lazy" && d.getter) {
    nullOnly(d.getter(), path, seen, found);
  } else if (d.innerType) {
    nullOnly(d.innerType, path, seen, found);
  }
}

describe("wire events read an omitted field as null", () => {
  it("has no field that accepts null but rejects being omitted", () => {
    const found: string[] = [];
    nullOnly(WireEventSchema, "event", new Set(), found);
    expect(found).toEqual([]);
  });

  it("parses a resources event the way the live connection sends it", () => {
    const snapshot = {
      max_live_processes: 8,
      memory_reserve_bytes: 1,
      default_process_memory_bytes: 1,
      memory_reservation_bytes: 1,
      memory_warn_percent: 90,
      memory_captain_ceiling_bytes: 1,
      host_ram_bytes: 1,
      memory_budget_bytes: 1,
      memory_ceiling_bytes: 1,
      live_processes: 0,
      memory_reserved_bytes: 0,
      memory_cap_bytes: 1,
      remaining_processes: 8,
      remaining_memory_bytes: 1,
      top_lines: [],
      docker: { running: 0, uncapped: 0, unattributed: 0, sampled_at: 1 },
    };
    const parsed = ResourcesEventSchema.parse({ type: "resources", snapshot });
    expect(parsed.snapshot.docker?.memory_used_bytes).toBeNull();
    expect(parsed.snapshot.busiest_line).toBeNull();
    expect(parsed.snapshot.sampled_at).toBeNull();
  });
});
