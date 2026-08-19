import { afterEach, describe, expect, it, vi } from "vitest";
import { clearStoredTokens, storeTokens } from "./http";
import { sendOffLine } from "./offline-wire";

class FakeSocket {
  static instances: FakeSocket[] = [];
  readonly sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  close(): void {
    /* the client closes after sending; the fake does not echo that close */
  }

  send(data: string): void {
    this.sent.push(data);
  }
}

afterEach(() => {
  clearStoredTokens();
  FakeSocket.instances = [];
  vi.unstubAllGlobals();
});

describe("sendOffLine", () => {
  it("retries access before refreshing and sends identity-free commands", async () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    storeTokens("expired", "refresh");
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        access_token: "fresh",
        refresh_token: "rotated",
        token_type: "bearer",
        user: { id: 1, email: "greg@example.com", handle: "greg" },
      }),
    });
    vi.stubGlobal("fetch", fetch);

    const sent = sendOffLine("line", { clientId: "browser" }, "heads up");
    const first = FakeSocket.instances[0];
    if (!first?.onclose || !first.onerror) throw new Error("missing initial socket");
    expect(first.url).toContain("token=expired");
    // Chromium can report a generic error before exposing the auth close code.
    first.onerror();
    first.onclose({ code: 4401 });

    await vi.waitFor(() => {
      expect(FakeSocket.instances).toHaveLength(2);
    });
    expect(fetch).not.toHaveBeenCalled();
    const sameTokenRetry = FakeSocket.instances[1];
    if (!sameTokenRetry?.onclose) throw new Error("missing same-token retry socket");
    expect(sameTokenRetry.url).toContain("token=expired");
    sameTokenRetry.onclose({ code: 4401 });

    await vi.waitFor(() => {
      expect(FakeSocket.instances).toHaveLength(3);
    });
    expect(fetch).toHaveBeenCalledOnce();
    const retry = FakeSocket.instances[2];
    if (!retry?.onopen || !retry.onmessage) throw new Error("missing retry socket");
    expect(retry.url).toContain("token=fresh");
    retry.onopen();
    retry.onmessage({
      data: JSON.stringify({
        type: "hello",
        conversation_id: "line",
        handle: "greg",
        version: "0.43.0",
        instance_name: null,
      }),
    });
    await sent;

    const frames = retry.sent.map((frame): unknown => JSON.parse(frame));
    expect(frames).toEqual([{ type: "hello", client_id: "browser" }, { body: "heads up" }]);
  });
});
