import { describe, expect, it } from "vitest";
import type { Conversation } from "./contracts";
import { applyLineLive } from "./line-live";

const conversations: Conversation[] = [
  { id: "one", name: "One", topic: "", created_at: 1, archived_at: null, live_count: 0 },
  { id: "two", name: "Two", topic: "", created_at: 2, archived_at: null, live_count: 1 },
];

describe("line live events", () => {
  it("patches only the named rail row", () => {
    const updated = applyLineLive(conversations, {
      type: "line_live",
      conversation_id: "one",
      live_count: 2,
    });
    expect(updated.map(({ id, live_count }) => ({ id, live_count }))).toEqual([
      { id: "one", live_count: 2 },
      { id: "two", live_count: 1 },
    ]);
  });
});
