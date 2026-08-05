import { describe, expect, it } from "vitest";
import { conversationRoute, routedConversationId } from "./routing";

describe("conversation routes", () => {
  it("round-trips an id", () => {
    expect(routedConversationId(conversationRoute("abc123"))).toBe("abc123");
  });

  it("round-trips an id needing escaping", () => {
    const id = "a b/c#d";
    expect(routedConversationId(conversationRoute(id))).toBe(id);
  });

  it("reads nothing from an empty or unrelated hash", () => {
    expect(routedConversationId("")).toBeNull();
    expect(routedConversationId("#/settings")).toBeNull();
    expect(routedConversationId("#/c/a/b")).toBeNull();
  });

  it("treats a malformed escape as no route rather than throwing", () => {
    expect(routedConversationId("#/c/%E0%A4%A")).toBeNull();
  });
});
