import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api.js";

function response(body, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api", () => {
  it("serializes JSON requests through the shared client", async () => {
    const fetch = vi.fn().mockResolvedValue(response({ id: "conv-1" }));
    vi.stubGlobal("fetch", fetch);

    await expect(api.createConversation("work room")).resolves.toEqual({ id: "conv-1" });
    expect(fetch).toHaveBeenCalledWith("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "work room" }),
    });
  });

  it("surfaces the server detail and status on an HTTP error", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(response({ detail: "that process is already live" }, { ok: false, status: 409 })),
    );

    await expect(api.resume("att-1")).rejects.toEqual(new ApiError("that process is already live", 409));
  });

  it("uses operation-specific wording for a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));

    await expect(api.attach("conv-1", { name: "sol" })).rejects.toMatchObject({
      name: "ApiError",
      message: "attach failed",
      status: 0,
    });
  });

  it("keeps fallback wording when an error body is not JSON", async () => {
    const reply = response(null, { ok: false, status: 502 });
    reply.json.mockRejectedValue(new SyntaxError("not JSON"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply));

    await expect(api.shutdown()).rejects.toMatchObject({
      message: "could not stop partyline",
      status: 502,
    });
  });

  it("does not parse a 204 response body", async () => {
    const reply = response(undefined, { status: 204 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply));

    await expect(api.detach("att-1")).resolves.toBeNull();
    expect(reply.json).not.toHaveBeenCalled();
  });
});
