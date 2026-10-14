import { describe, expect, it } from "vitest";
import { AttachmentSchema } from "./attachment-contracts";
import { BridgeLogEntrySchema, BridgeSchema, bridgeLabel } from "./bridge-api";
import { treeRootId } from "./line-hierarchy";

const side = (n: string) => ({ conv_id: `c-${n}`, conv_name: `Line ${n}`, attachment_id: `a-${n}`, name: n });

describe("bridge schemas", () => {
  it("accepts a bridge whose null close fields the server omitted", () => {
    const parsed = BridgeSchema.parse({
      id: "b1",
      opened_at: 1,
      opened_by: "greg",
      sides: [side("x"), side("y")],
    });
    expect(parsed.closed_at).toBeUndefined();
    expect(
      BridgeSchema.parse({ ...parsed, closed_at: null, closed_by: null, close_reason: null }).closed_by,
    ).toBe(null);
  });

  it("requires exactly two sides", () => {
    expect(() => BridgeSchema.parse({ id: "b", opened_at: 1, opened_by: "g", sides: [side("x")] })).toThrow();
  });

  it("accepts a log row without its source line", () => {
    const row = BridgeLogEntrySchema.parse({ id: 1, conv_id: "c", sender: "sol", body: "hi", created_at: 2 });
    expect(row.source_conv_name).toBeUndefined();
  });

  it("reads the attachment bridge field present, null or omitted", () => {
    const base = {
      id: "a",
      conv_id: "c",
      name: "sol",
      adapter: "codex",
      command: [],
      cwd: "/",
      status: "running",
      last_seen: 0,
      created_at: 1,
    };
    expect(AttachmentSchema.parse(base).bridge).toBeUndefined();
    expect(AttachmentSchema.parse({ ...base, bridge: null }).bridge).toBeNull();
    const bridge = {
      bridge_id: "b",
      peer_name: "fable",
      peer_attachment_id: "p",
      peer_conv_id: "pc",
      peer_conv_name: "tool",
    };
    expect(AttachmentSchema.parse({ ...base, bridge }).bridge?.peer_name).toBe("fable");
  });

  it("words the badge tooltip", () => {
    expect(
      bridgeLabel({
        bridge_id: "b",
        peer_name: "fable",
        peer_attachment_id: "p",
        peer_conv_id: "pc",
        peer_conv_name: "tool",
      }),
    ).toBe("bridged with @fable on «tool»");
  });
});

describe("treeRootId", () => {
  const lines = [{ id: "r" }, { id: "k", parent_id: "r" }, { id: "g", parent_id: "k" }, { id: "o" }];
  it("finds a line's root, and keeps separate trees apart", () => {
    expect(treeRootId("g", lines)).toBe("r");
    expect(treeRootId("r", lines)).toBe("r");
    expect(treeRootId("o", lines)).toBe("o");
  });
  it("survives a cycle and an unknown parent", () => {
    expect(
      treeRootId("a", [
        { id: "a", parent_id: "b" },
        { id: "b", parent_id: "a" },
      ]),
    ).toBeTypeOf("string");
    expect(treeRootId("z", [{ id: "z", parent_id: "missing" }])).toBe("z");
  });
});
