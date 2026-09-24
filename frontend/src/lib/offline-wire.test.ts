import { afterEach, describe, expect, it, vi } from "vitest";
import { clearStoredTokens, storeTokens } from "./http";
import { sendOffLine, sendMessage } from "./offline-wire";

afterEach(() => {
  clearStoredTokens();
  vi.unstubAllGlobals();
});

describe("sendMessage", () => {
  it("posts through REST with auth recovery", async () => {
    storeTokens("expired", "refresh");
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: vi.fn().mockResolvedValue({ detail: "expired" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({
          access_token: "fresh",
          refresh_token: "rotated",
          token_type: "bearer",
          user: { id: 1, email: "greg@example.com", handle: "greg" },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({
          id: 9,
          conv_id: "line",
          sender: "greg",
          sender_type: "human",
          body: "heads up",
          created_at: 1,
          files: [],
        }),
      });
    vi.stubGlobal("fetch", fetch);

    const message = await sendMessage("line", "heads up");

    expect(message.body).toBe("heads up");
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls[2]?.[0]).toBe("/api/conversations/line/messages");
  });
});

describe("sendOffLine", () => {
  it("delegates to the REST sender", async () => {
    storeTokens("token", "refresh");
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        id: 2,
        conv_id: "other",
        sender: "greg",
        sender_type: "human",
        body: "ping",
        created_at: 1,
        files: [],
      }),
    });
    vi.stubGlobal("fetch", fetch);

    await sendOffLine("other", { clientId: "browser" }, "ping");

    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0]?.[0]).toBe("/api/conversations/other/messages");
  });
});
