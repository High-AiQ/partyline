import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import {
  ApiError,
  clearStoredTokens,
  configureAuthHandlers,
  isAuthStorageKey,
  readAccessToken,
  recoverSocketAuthentication,
  refreshAccessToken,
  request,
  requestBlob,
  storeTokens,
} from "./http";

interface MockResponseOptions {
  ok?: boolean;
  status?: number;
}

interface MockResponse extends Pick<Response, "ok" | "status" | "json"> {
  json: ReturnType<typeof vi.fn>;
}

const OkSchema = z.object({ ok: z.literal(true) });

const user = { id: 1, email: "greg@example.com", handle: "greg" };
const rotated = {
  access_token: "access-new",
  refresh_token: "refresh-new",
  token_type: "bearer" as const,
  user,
};

function response(body: unknown, { ok = true, status = 200 }: MockResponseOptions = {}): MockResponse {
  return { ok, status, json: vi.fn().mockResolvedValue(body) };
}

afterEach(() => {
  clearStoredTokens();
  configureAuthHandlers({ onRefreshed: () => undefined, onSessionCleared: () => undefined });
  vi.unstubAllGlobals();
});

describe("authenticated HTTP transport", () => {
  it("recognizes only the persisted auth keys for cross-tab synchronization", () => {
    expect(isAuthStorageKey("partyline_access_token")).toBe(true);
    expect(isAuthStorageKey("partyline_refresh_token")).toBe(true);
    expect(isAuthStorageKey("partyline_session_id")).toBe(true);
    expect(isAuthStorageKey("partyline_client_id")).toBe(false);
    expect(isAuthStorageKey(null)).toBe(false);
  });

  it("adds the access token to REST requests", async () => {
    storeTokens("access-old", "refresh-old");
    const fetch = vi.fn().mockResolvedValue(response({ ok: true }));
    vi.stubGlobal("fetch", fetch);

    await request("/api/running", { schema: OkSchema });

    expect(fetch).toHaveBeenCalledWith("/api/running", {
      method: "GET",
      headers: { Authorization: "Bearer access-old" },
    });
  });

  it("downloads binary content with a header instead of a tokenized URL", async () => {
    storeTokens("access-old", "refresh-old");
    const blob = new Blob(["image"]);
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: vi.fn().mockResolvedValue(blob),
    });
    vi.stubGlobal("fetch", fetch);

    await expect(requestBlob("/api/media/image/original")).resolves.toBe(blob);
    expect(fetch).toHaveBeenCalledWith("/api/media/image/original", {
      headers: { Authorization: "Bearer access-old" },
    });
  });

  it("retries a 4401 socket with the accepted access token before refreshing", async () => {
    storeTokens("still-valid", "refresh");
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);

    await expect(recoverSocketAuthentication("still-valid", "initial")).resolves.toEqual({
      retry: true,
      phase: "retried-access",
    });
    expect(fetch).not.toHaveBeenCalled();
    expect(readAccessToken()).toBe("still-valid");
  });

  it("keeps a socket session when refresh fails transiently", async () => {
    storeTokens("still-valid", "refresh");
    const cleared = vi.fn();
    configureAuthHandlers({ onRefreshed: vi.fn(), onSessionCleared: cleared });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response({ detail: "refresh unavailable" }, { ok: false, status: 500 })),
    );

    await expect(recoverSocketAuthentication("still-valid", "retried-access")).rejects.toEqual(
      new ApiError("refresh unavailable", 500),
    );
    expect(cleared).not.toHaveBeenCalled();
    expect(readAccessToken()).toBe("still-valid");
  });

  it("clears a socket session when the refresh credential is rejected", async () => {
    storeTokens("expired", "invalid-refresh");
    const cleared = vi.fn(() => {
      clearStoredTokens();
    });
    configureAuthHandlers({ onRefreshed: vi.fn(), onSessionCleared: cleared });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response({ detail: "invalid refresh" }, { ok: false, status: 401 })),
    );

    await expect(recoverSocketAuthentication("expired", "retried-access")).resolves.toEqual({
      retry: false,
      phase: "initial",
    });
    expect(cleared).toHaveBeenCalledOnce();
    expect(readAccessToken()).toBeNull();
  });

  it("keeps a binary-download session when refresh fails transiently", async () => {
    storeTokens("expired", "refresh");
    const cleared = vi.fn();
    configureAuthHandlers({ onRefreshed: vi.fn(), onSessionCleared: cleared });
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(response({ detail: "expired" }, { ok: false, status: 401 }))
      .mockResolvedValueOnce(response({ detail: "refresh unavailable" }, { ok: false, status: 500 }));
    vi.stubGlobal("fetch", fetch);

    await expect(requestBlob("/api/media/image/original")).rejects.toEqual(
      new ApiError("refresh unavailable", 500),
    );
    expect(cleared).not.toHaveBeenCalled();
    expect(readAccessToken()).toBe("expired");
  });

  it("keeps the session when the network, rather than authentication, fails", async () => {
    storeTokens("access-old", "refresh-old");
    const cleared = vi.fn();
    configureAuthHandlers({ onRefreshed: vi.fn(), onSessionCleared: cleared });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    await expect(request("/api/running", { schema: OkSchema })).rejects.toEqual(
      new ApiError("the line is not reachable", 0),
    );
    expect(cleared).not.toHaveBeenCalled();
    expect(readAccessToken()).toBe("access-old");
  });

  it("shares one rotating refresh across concurrent 401 responses", async () => {
    storeTokens("access-old", "refresh-old");
    let protectedCalls = 0;
    let refreshCalls = 0;
    const refreshed = vi.fn();
    configureAuthHandlers({ onRefreshed: refreshed, onSessionCleared: vi.fn() });
    const fetch = vi.fn((path: string) => {
      if (path === "/api/auth/refresh") {
        refreshCalls++;
        return Promise.resolve(response(rotated));
      }
      protectedCalls++;
      return Promise.resolve(
        protectedCalls <= 2
          ? response({ detail: "expired" }, { ok: false, status: 401 })
          : response({ ok: true }),
      );
    });
    vi.stubGlobal("fetch", fetch);

    await expect(
      Promise.all([request("/api/one", { schema: OkSchema }), request("/api/two", { schema: OkSchema })]),
    ).resolves.toEqual([{ ok: true }, { ok: true }]);

    expect(refreshCalls).toBe(1);
    expect(refreshed).toHaveBeenCalledOnce();
    expect(readAccessToken()).toBe("access-new");
    expect(fetch).toHaveBeenCalledWith(
      "/api/auth/refresh",
      expect.objectContaining({ body: JSON.stringify({ refresh_token: "refresh-old" }) }),
    );
  });

  it("surfaces the retried request failure instead of masking it as the original 401", async () => {
    storeTokens("access-old", "refresh-old");
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(response({ detail: "expired" }, { ok: false, status: 401 }))
      .mockResolvedValueOnce(response(rotated))
      .mockResolvedValueOnce(response({ detail: "server broke" }, { ok: false, status: 500 }));
    vi.stubGlobal("fetch", fetch);

    await expect(request("/api/protected", { schema: OkSchema })).rejects.toEqual(
      new ApiError("server broke", 500),
    );
  });

  it("clears the current session when refresh cannot recover a 401", async () => {
    storeTokens("access-old", "refresh-old");
    const cleared = vi.fn(() => {
      clearStoredTokens();
    });
    configureAuthHandlers({ onRefreshed: vi.fn(), onSessionCleared: cleared });
    const fetch = vi.fn((path: string) =>
      Promise.resolve(
        response(
          { detail: path === "/api/auth/refresh" ? "invalid refresh" : "expired" },
          { ok: false, status: 401 },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(request("/api/protected", { schema: OkSchema })).rejects.toEqual(
      new ApiError("expired", 401),
    );
    expect(cleared).toHaveBeenCalledOnce();
    expect(readAccessToken()).toBeNull();
  });

  it("does not let a stale failed refresh clear a newer login", async () => {
    storeTokens("access-old", "refresh-old");
    const cleared = vi.fn();
    configureAuthHandlers({ onRefreshed: vi.fn(), onSessionCleared: cleared });
    const fetch = vi.fn((path: string) => {
      if (path === "/api/auth/refresh") {
        storeTokens("fresh-login", "fresh-refresh");
        return Promise.resolve(response({ detail: "old refresh expired" }, { ok: false, status: 401 }));
      }
      return Promise.resolve(response({ detail: "expired" }, { ok: false, status: 401 }));
    });
    vi.stubGlobal("fetch", fetch);

    await expect(request("/api/protected", { schema: OkSchema })).rejects.toBeInstanceOf(ApiError);
    expect(cleared).not.toHaveBeenCalled();
    expect(readAccessToken()).toBe("fresh-login");
  });

  it("does not let a stale successful refresh overwrite a newer login", async () => {
    storeTokens("access-old", "refresh-old");
    let finishOld: ((value: MockResponse) => void) | undefined;
    const oldResponse = new Promise<MockResponse>((resolve) => {
      finishOld = resolve;
    });
    const fetch = vi.fn().mockReturnValue(oldResponse);
    vi.stubGlobal("fetch", fetch);

    const oldRefresh = refreshAccessToken();
    storeTokens("fresh-login", "fresh-refresh");
    finishOld?.(response(rotated));

    await expect(oldRefresh).rejects.toBeInstanceOf(Error);
    expect(readAccessToken()).toBe("fresh-login");
  });

  it("accepts a same-session rotation that raced with another tab", async () => {
    storeTokens("access-old", "refresh-old");
    let finish: ((value: MockResponse) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<MockResponse>((resolve) => {
          finish = resolve;
        }),
      ),
    );

    const refresh = refreshAccessToken();
    localStorage.setItem("partyline_access_token", "other-tab-access");
    localStorage.setItem("partyline_refresh_token", "other-tab-refresh");
    finish?.(response(rotated));

    await expect(refresh).resolves.toBe("access-new");
    expect(readAccessToken()).toBe("access-new");
  });

  it("does not share a refresh flight across different signed-in sessions", async () => {
    storeTokens("access-old", "refresh-old");
    const fetch = vi.fn().mockResolvedValue(response(rotated));
    vi.stubGlobal("fetch", fetch);

    const oldRefresh = refreshAccessToken();
    storeTokens("fresh-login", "fresh-refresh");
    const newRefresh = refreshAccessToken();

    await expect(oldRefresh).rejects.toBeInstanceOf(Error);
    await expect(newRefresh).resolves.toBe("access-new");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
