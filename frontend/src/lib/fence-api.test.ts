import { afterEach, describe, expect, it, vi } from "vitest";
import { fenceApi } from "./fence-api";

describe("fence status API", () => {
  afterEach(() => vi.restoreAllMocks());

  it("validates and returns the startup probe and remedy", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ok: false,
            backend: "bubblewrap",
            platform: "linux",
            reason: "user namespaces are disabled",
            remedy: "apt-get install -y bubblewrap",
          }),
        ),
      ),
    );

    await expect(fenceApi.status()).resolves.toMatchObject({
      ok: false,
      remedy: "apt-get install -y bubblewrap",
    });
    expect(fetch).toHaveBeenCalledWith("/api/fence/status", { method: "GET" });
  });
});
