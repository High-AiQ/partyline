import { afterEach, describe, expect, it, vi } from "vitest";
import { writeSetApi } from "./write-set-api";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("write-set requests", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("approves and declines by request id on a line", async () => {
    const fetch = vi.fn().mockResolvedValue(response({ request: null }));
    vi.stubGlobal("fetch", fetch);
    await expect(writeSetApi.approve("line", "abc")).resolves.toEqual({ request: null });
    expect(fetch).toHaveBeenCalledWith("/api/conversations/line/write-set/request/abc/approve", {
      method: "POST",
    });
    fetch.mockResolvedValue(response({ request: null }));
    await expect(writeSetApi.decline("line", "abc")).resolves.toEqual({ request: null });
    expect(fetch).toHaveBeenCalledWith("/api/conversations/line/write-set/request/abc", {
      method: "DELETE",
    });
  });
});
