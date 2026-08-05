import { describe, expect, it } from "vitest";
import { WireEventSchema, WireReattachCommandSchema } from "./contracts";

const offer = {
  type: "reattach_offer",
  conversation_id: "line",
  token: "offer-token",
  attachments: [{ id: "att-1", name: "sol", adapter: "codex" }],
  debrief: "Continue the review.",
};

describe("restart wire contracts", () => {
  it("accepts the named same-line offer payload", () => {
    expect(WireEventSchema.parse(offer)).toEqual(offer);
  });

  it("rejects an offer without the token that binds the decision", () => {
    const missingToken = {
      type: offer.type,
      conversation_id: offer.conversation_id,
      attachments: offer.attachments,
      debrief: offer.debrief,
    };

    expect(() => WireEventSchema.parse(missingToken)).toThrow();
  });

  it("allows only an explicit accept or cancel decision", () => {
    expect(
      WireReattachCommandSchema.parse({
        type: "reattach",
        token: "offer-token",
        action: "accept",
      }),
    ).toEqual({ type: "reattach", token: "offer-token", action: "accept" });
    expect(() =>
      WireReattachCommandSchema.parse({
        type: "reattach",
        token: "offer-token",
        action: "later",
      }),
    ).toThrow();
  });
});
