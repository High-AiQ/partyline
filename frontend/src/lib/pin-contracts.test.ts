import { describe, expect, it } from "vitest";
import { PinListSchema } from "./pin-contracts";
import { WireEventSchema } from "./contracts";

const pin = {
  conversation_id: "line",
  message_id: 5,
  created_at: 1,
  message_available: true,
  file_count: 0,
};

describe("pin contracts", () => {
  it("defaults omitted wire aliases and message text to null", () => {
    const event = WireEventSchema.parse({
      type: "pins_changed",
      conversation_id: "line",
      pins: [pin],
    });

    expect(event).toEqual({
      type: "pins_changed",
      conversation_id: "line",
      pins: [{ ...pin, alias: null, message_text: null }],
    });
  });

  it("keeps a configured alias from the wire", () => {
    const event = WireEventSchema.parse({
      type: "pins_changed",
      conversation_id: "line",
      pins: [{ ...pin, alias: "Decision log", message_text: "hi" }],
    });

    expect(event).toMatchObject({ pins: [{ alias: "Decision log", message_text: "hi" }] });
  });

  it("accepts REST pins with explicit nulls", () => {
    const pins = PinListSchema.parse([{ ...pin, alias: null, message_text: null }]);

    expect(pins[0]).toMatchObject({ alias: null, message_text: null });
  });
});
