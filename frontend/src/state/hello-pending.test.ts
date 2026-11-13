import { afterEach, describe, expect, it, vi } from "vitest";
import { connectAccountWire } from "./account-wire.svelte.js";
import { restart } from "./restart.svelte.js";
import { room } from "./room.svelte.js";
import { wire } from "./wire.svelte.js";
import { api } from "../lib/api";
import { fenceApi } from "../lib/fence-api";
import { restartApi } from "../lib/restart-api";
import { WireEventSchema } from "../lib/events";

class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState: number = WebSocket.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  close(): void {
    this.readyState = WebSocket.CLOSED;
  }

  send(): void {
    /* the handshake command is not under test */
  }
}

const healthyFence = { ok: true, backend: "bubblewrap", platform: "linux", reason: "", remedy: "" };

const pending = {
  id: "r1",
  conversation_id: "line",
  requester: "opus",
  reason: "deploy 2.117.1",
  created_at: 1,
};

function accountHello(extra: Record<string, unknown>): void {
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("location", { protocol: "https:", host: "partyline.example" });
  wire.connect("~account", { clientId: "tab" }, () => undefined);
  const socket = FakeSocket.instances[0];
  if (!socket?.onopen || !socket.onmessage) throw new Error("missing socket handlers");
  socket.onopen();
  socket.onmessage({
    data: JSON.stringify({
      type: "hello",
      conversation_id: "~account",
      handle: "greg",
      version: "2.117.1",
      ...extra,
    }),
  });
}

afterEach(() => {
  wire.disconnect();
  restart.apply(null);
  FakeSocket.instances = [];
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("pending restart replay on the handshake", () => {
  it("shows the restart banner even when the line list cannot be read", async () => {
    // The incident: a list that failed to parse hid the restart that would fix it.
    vi.spyOn(api, "conversations").mockRejectedValue(new Error("unreadable list"));
    vi.spyOn(fenceApi, "status").mockResolvedValue(healthyFence);
    const ask = vi.spyOn(restartApi, "pending");
    await expect(room.loadConversations()).rejects.toThrow("unreadable list");

    accountHello({ restart_request: pending });

    expect(restart.request?.reason).toBe("deploy 2.117.1");
    expect(ask).not.toHaveBeenCalled();
  });

  it("clears a banner decided while the tab was away", () => {
    vi.spyOn(fenceApi, "status").mockResolvedValue(healthyFence);
    restart.apply(pending);

    accountHello({ restart_request: null });

    expect(restart.request).toBeNull();
  });

  it("asks an older server that does not replay it, once", async () => {
    vi.spyOn(fenceApi, "status").mockResolvedValue(healthyFence);
    const ask = vi.spyOn(restartApi, "pending").mockResolvedValue({ request: pending });

    accountHello({});

    await vi.waitFor(() => {
      expect(restart.request?.id).toBe("r1");
    });
    expect(ask).toHaveBeenCalledOnce();
  });
});

describe("account wire", () => {
  it("applies a restart request filed while no line is open", () => {
    const connect = vi.spyOn(wire, "connect").mockImplementation(() => undefined);
    connectAccountWire({ clientId: "tab" }, vi.fn());
    const onEvent = connect.mock.calls[0]?.[2];
    if (!onEvent) throw new Error("missing account event handler");

    onEvent(WireEventSchema.parse({ type: "restart_request", request: pending }), {
      wasReady: true,
      claimRejected: false,
      rejectClaim: vi.fn(),
    });

    expect(restart.request?.id).toBe("r1");
  });
});
