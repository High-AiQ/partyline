import { afterEach, describe, expect, it, vi } from "vitest";
import { restartApi } from "./restart-api";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("restart requests", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("approves and declines by request id", async () => {
    const fetch = vi.fn().mockResolvedValue(response({ request: null }));
    vi.stubGlobal("fetch", fetch);
    await expect(restartApi.approve("abc")).resolves.toEqual({ request: null });
    expect(fetch).toHaveBeenCalledWith("/api/restart-request/abc/approve", { method: "POST" });
    fetch.mockResolvedValue(response({ request: null }));
    await expect(restartApi.decline("abc")).resolves.toEqual({ request: null });
    expect(fetch).toHaveBeenCalledWith("/api/restart-request/abc", { method: "DELETE" });
  });
});
