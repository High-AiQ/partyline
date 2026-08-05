import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiContractError, ApiError } from "./api";
import type { AttachPayload, PresetDraft } from "./api";
import type { Conversation } from "./contracts";

interface MockResponseOptions {
  ok?: boolean;
  status?: number;
}

interface MockResponse extends Pick<Response, "ok" | "status" | "json"> {
  json: ReturnType<typeof vi.fn>;
}

const conversation: Conversation = {
  id: "conv-1",
  name: "work room",
  topic: "",
  created_at: 1,
  archived_at: null,
};

const attachPayload: AttachPayload = {
  name: "sol",
  adapter: "codex",
  command: "codex",
  cwd: "/tmp/work",
};

function response(body: unknown, { ok = true, status = 200 }: MockResponseOptions = {}): MockResponse {
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
    const fetch = vi.fn().mockResolvedValue(response(conversation));
    vi.stubGlobal("fetch", fetch);

    await expect(api.createConversation("work room")).resolves.toEqual(conversation);
    expect(fetch).toHaveBeenCalledWith("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "work room" }),
    });
  });

  it("rejects a successful response that violates its named contract", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ id: "conv-1" })));

    await expect(api.createConversation("work room")).rejects.toMatchObject({
      name: "ApiContractError",
      path: "/api/conversations",
    } satisfies Partial<ApiContractError>);
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

    await expect(api.attach("conv-1", attachPayload)).rejects.toMatchObject({
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

  it("does not send a new-preset id that is absent", async () => {
    const preset: PresetDraft = {
      title: "review",
      name: "sol",
      adapter: "codex",
      command: "codex",
    };
    const saved = { id: "preset-1", ...preset, created_at: 1 };
    const fetch = vi.fn().mockResolvedValue(response(saved));
    vi.stubGlobal("fetch", fetch);

    await expect(api.savePreset(preset)).resolves.toEqual(saved);
    expect(fetch).toHaveBeenCalledWith("/api/presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(preset),
    });
  });
});
