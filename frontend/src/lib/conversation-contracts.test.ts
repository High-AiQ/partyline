import { describe, expect, it, vi } from "vitest";
import { ConversationListSchema, ConversationSchema } from "./conversation-contracts";

const line = { id: "a", name: "partyline dev", topic: "", created_at: 1 };

describe("conversation contracts across a release skew", () => {
  it("reads a captain style this bundle no longer knows as absent", () => {
    // A pulled checkout serves the new UI while the old server still says manager_tree.
    const parsed = ConversationSchema.parse({ ...line, captain_mode: "manager_tree" });
    expect(parsed.captain_mode).toBeUndefined();
    expect(ConversationSchema.parse({ ...line, captain_mode: "orchestrator" }).captain_mode).toBe(
      "orchestrator",
    );
  });

  it("reads unknown task status and mode as no task rather than failing the row", () => {
    const parsed = ConversationSchema.parse({ ...line, task_status: "parked", task_mode: "turbo" });
    expect(parsed.task_status).toBeNull();
    expect(parsed.task_mode).toBeNull();
  });

  it("drops only the unreadable row from the list", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const rows = ConversationListSchema.parse([line, { id: "broken" }, { ...line, id: "b" }]);
    expect(rows.map((row) => row.id)).toEqual(["a", "b"]);
    expect(warn).toHaveBeenCalledOnce();
    warn.mockRestore();
  });
});
