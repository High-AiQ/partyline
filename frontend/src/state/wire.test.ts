import { describe, expect, it } from "vitest";
import { authenticatedResourceUrl, authenticatedSocketUrl } from "../lib/socket-auth";

describe("authenticatedSocketUrl", () => {
  it("carries the encoded access token in the browser-compatible query", () => {
    expect(
      authenticatedSocketUrl("/ws/line one", { protocol: "https:", host: "partyline.test" }, "jwt+/="),
    ).toBe("wss://partyline.test/ws/line one?token=jwt%2B%2F%3D");
  });

  it("does not invent a token when none is available", () => {
    expect(authenticatedSocketUrl("/ws/line", { protocol: "http:", host: "127.0.0.1:8642" }, null)).toBe(
      "ws://127.0.0.1:8642/ws/line",
    );
  });

  it("authenticates browser-loaded media while preserving an existing query", () => {
    expect(authenticatedResourceUrl("/api/media/image/slim?download=1", "jwt+/=")).toBe(
      "/api/media/image/slim?download=1&token=jwt%2B%2F%3D",
    );
  });
});
