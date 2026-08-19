import { afterEach, describe, expect, it, vi } from "vitest";
import { beginHandshake, discardGeneration, newOutputGate, paintIsCurrent } from "../lib/terminal";
import { clearStoredTokens, storeTokens } from "../lib/http";
import { TERMINAL_RETRY_MS, TerminalStream } from "./terminal.svelte.js";

class FakeSocket {
  static instances: FakeSocket[] = [];
  binaryType = "";
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }
  close(): void {
    /* the real socket is closed by the stream; we do not echo onclose */
  }
  send(): void {
    /* unused in this test */
  }
}

describe("TerminalStream retry", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    clearStoredTokens();
    FakeSocket.instances = [];
  });

  it("invalidates an in-flight paint when the stream retries on its own timer", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);

    let gate = newOutputGate();
    let paintId = 0;
    const onGeneration = vi.fn((generation: number) => {
      gate = discardGeneration(gate, generation);
    });
    const stream = new TerminalStream();
    stream.connect("att-1", {
      onHandshake() {
        gate = beginHandshake(gate, stream.generation);
        paintId = gate.paintId;
      },
      onBytes() {
        /* live bytes are not under test */
      },
      onUnavailable() {
        /* a 1000 close after handshake retries instead */
      },
      onGeneration,
    });

    const first = FakeSocket.instances[0];
    if (!first?.onmessage || !first.onclose) throw new Error("expected a live socket");
    first.onmessage({ data: '{"cols":80,"rows":24}' });
    first.onmessage({ data: "screen" });
    expect(onGeneration).toHaveBeenCalledTimes(1);
    expect(onGeneration).toHaveBeenLastCalledWith(1);
    expect(paintIsCurrent(gate, 1, paintId)).toBe(true);
    first.onclose({ code: 1000 });

    vi.advanceTimersByTime(TERMINAL_RETRY_MS);
    expect(FakeSocket.instances.length).toBe(2);
    expect(onGeneration).toHaveBeenCalledTimes(2);
    expect(onGeneration).toHaveBeenLastCalledWith(2);
    expect(paintIsCurrent(gate, 1, paintId)).toBe(false);
  });

  it("retries the access token before refreshing a twice-rejected socket", async () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    storeTokens("expired-access", "valid-refresh");
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        access_token: "fresh-access",
        refresh_token: "rotated-refresh",
        token_type: "bearer",
        user: { id: 1, email: "greg@example.com", handle: "greg" },
      }),
    });
    vi.stubGlobal("fetch", fetch);

    const stream = new TerminalStream();
    stream.connect("att-1", {
      onHandshake() {
        /* reconnect is the behavior under test */
      },
      onBytes() {
        /* reconnect is the behavior under test */
      },
      onUnavailable() {
        /* a 4401 close refreshes instead */
      },
      onGeneration() {
        /* reconnect is observed through FakeSocket instances */
      },
    });
    const first = FakeSocket.instances[0];
    if (!first?.onclose) throw new Error("expected a live socket");
    first.onclose({ code: 4401 });

    await vi.waitFor(() => {
      expect(FakeSocket.instances).toHaveLength(2);
    });
    expect(fetch).not.toHaveBeenCalled();
    expect(FakeSocket.instances[1]?.url).toContain("token=expired-access");

    const retry = FakeSocket.instances[1];
    if (!retry?.onclose) throw new Error("expected the access-token retry");
    retry.onclose({ code: 4401 });
    await vi.waitFor(() => {
      expect(FakeSocket.instances).toHaveLength(3);
    });
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith(
      "/api/auth/refresh",
      expect.objectContaining({ body: JSON.stringify({ refresh_token: "valid-refresh" }) }),
    );
    expect(FakeSocket.instances[2]?.url).toContain("token=fresh-access");
  });
});
