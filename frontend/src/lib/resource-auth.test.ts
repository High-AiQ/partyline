import { afterEach, describe, expect, it, vi } from "vitest";
import { clearStoredTokens, configureAuthHandlers, storeTokens } from "./http";
import { installResourceAuthRecovery } from "./resource-auth";

const rotated = {
  access_token: "access-new",
  refresh_token: "refresh-new",
  token_type: "bearer" as const,
  user: { id: 1, email: "greg@example.com", handle: "greg" },
};

function stubRefresh(status: number, body: unknown = rotated): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: status === 200, status, json: () => Promise.resolve(body) }),
  );
}

function attached(src: string): HTMLImageElement {
  const image = document.createElement("img");
  image.src = src;
  document.body.appendChild(image);
  return image;
}

afterEach(() => {
  document.body.innerHTML = "";
  clearStoredTokens();
  configureAuthHandlers({ onRefreshed: () => undefined, onSessionCleared: () => undefined });
  vi.unstubAllGlobals();
});

describe("resource auth recovery", () => {
  it("refreshes and re-derives a tokened source after a resource error", async () => {
    storeTokens("access-stale", "refresh-old");
    stubRefresh(200);
    const stop = installResourceAuthRecovery();
    const image = attached("/api/media/abc/thumb?token=access-stale");

    image.dispatchEvent(new Event("error"));

    await vi.waitFor(() => {
      expect(image.src).toContain("token=access-new");
    });
    expect(image.getAttribute("data-auth-recovered")).toBe("");
    stop();
  });

  it("recovers each element exactly once, so a broken resource cannot loop", async () => {
    storeTokens("access-stale", "refresh-old");
    stubRefresh(200);
    const stop = installResourceAuthRecovery();
    const image = attached("/api/media/abc/thumb?token=access-stale");

    image.dispatchEvent(new Event("error"));
    await vi.waitFor(() => {
      expect(image.src).toContain("token=access-new");
    });
    image.dispatchEvent(new Event("error"));
    await Promise.resolve();

    expect(image.src).toContain("token=access-new");
    expect(fetch).toHaveBeenCalledTimes(1);
    stop();
  });

  it("leaves resources without a token parameter untouched", async () => {
    storeTokens("access-stale", "refresh-old");
    stubRefresh(200);
    const stop = installResourceAuthRecovery();
    const image = attached("/assets/logo.png");

    image.dispatchEvent(new Event("error"));
    await Promise.resolve();

    expect(image.src).toBe("http://localhost:3000/assets/logo.png");
    expect(fetch).not.toHaveBeenCalled();
    stop();
  });

  it("does not rewrite the source when the refresh itself fails", async () => {
    storeTokens("access-stale", "refresh-old");
    stubRefresh(401, { detail: "expired" });
    const stop = installResourceAuthRecovery();
    const image = attached("/api/media/abc/thumb?token=access-stale");

    image.dispatchEvent(new Event("error"));
    await Promise.resolve();

    expect(image.src).toContain("token=access-stale");
    expect(image.hasAttribute("data-auth-recovered")).toBe(false);
    stop();
  });
});
