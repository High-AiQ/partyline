import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiContractError, ApiError } from "./api";
import type { AttachPayload, PresetDraft } from "./api";
import type { Attachment, Conversation } from "./contracts";
import type { RestartPlan, RestartPlanRequest } from "./contracts";

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

const attachment: Attachment = {
  id: "att-1",
  conv_id: "conv-1",
  name: "sol",
  adapter: "codex",
  command: ["codex"],
  cwd: "/tmp/work",
  status: "detached",
  last_seen: 0,
  created_at: 1,
  cli_session: "session-1",
};

const restartRequest: RestartPlanRequest = {
  conversation_id: "conv-1",
  debrief: "Continue the strict TypeScript review.",
};

const restartPlan: RestartPlan = {
  ...restartRequest,
  token: "offer-token",
  attachments: [{ id: "att-1", name: "sol", adapter: "codex" }],
};

function response(body: unknown, { ok = true, status = 200 }: MockResponseOptions = {}): MockResponse {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
  };
}

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("api", () => {
  it("uploads files and optional metadata as multipart form data", async () => {
    const file = {
      id: "file-1",
      kind: "image",
      filename: "signal.png",
      title: "Signal map",
      description: "The partyline process topology",
      mime: "image/png",
      bytes: 256,
      width: 1200,
      height: 800,
      thumb: null,
      slim: null,
      urls: {
        original: "http://localhost/api/media/file-1/original",
        thumb: "http://localhost/api/media/file-1/thumb",
        slim: null,
      },
    };
    const uploaded = {
      message: {
        id: 8,
        conv_id: "conv-1",
        sender: "greg",
        sender_type: "human" as const,
        body: "Topology\n📷 Signal map · 1200×800 · thumb: http://localhost/thumb",
        created_at: 1,
        files: [file],
      },
      files: [file],
    };
    const fetch = vi
      .fn<(path: string, init: RequestInit) => Promise<MockResponse>>()
      .mockResolvedValue(response(uploaded));
    vi.stubGlobal("fetch", fetch);
    const upload = new File(["image bytes"], "signal.png", { type: "image/png" });

    await expect(
      api.uploadFiles("conv-1", {
        files: [upload],
        body: "Topology",
        title: "Signal map",
        description: "The partyline process topology",
      }),
    ).resolves.toEqual(uploaded);

    const call = fetch.mock.calls[0];
    expect(call?.[0]).toBe("/api/conversations/conv-1/files");
    const init = call?.[1];
    expect(init?.headers).toBeUndefined();
    if (!(init?.body instanceof FormData)) throw new Error("expected multipart body");
    expect(init.body.get("file")).toBe(upload);
    expect(init.body.has("sender")).toBe(false);
    expect(init.body.get("body")).toBe("Topology");
    expect(init.body.get("title")).toBe("Signal map");
    expect(init.body.get("description")).toBe("The partyline process topology");
  });

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

  it("schedules a same-line restart plan with its continuation debrief", async () => {
    const fetch = vi.fn().mockResolvedValue(response(restartPlan));
    vi.stubGlobal("fetch", fetch);

    await expect(api.planRestart(restartRequest)).resolves.toEqual(restartPlan);
    expect(fetch).toHaveBeenCalledWith("/api/restart-plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(restartRequest),
    });
  });

  it("patches a stopped jack command through the attachment contract", async () => {
    const updated = { ...attachment, command: ["codex", "--model", "new"] };
    const fetch = vi.fn().mockResolvedValue(response(updated));
    vi.stubGlobal("fetch", fetch);

    await expect(api.editAttachmentCommand("att-1", { command: "codex --model new" })).resolves.toEqual(
      updated,
    );
    expect(fetch).toHaveBeenCalledWith("/api/attachments/att-1", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: "codex --model new" }),
    });
  });

  it("optionally persists reattachment in the shutdown request", async () => {
    const result = { ok: true as const, stopping: ["sol"], reattach: restartPlan };
    const fetch = vi.fn().mockResolvedValue(response(result));
    vi.stubGlobal("fetch", fetch);

    await expect(api.shutdown(restartRequest)).resolves.toEqual(result);
    expect(fetch).toHaveBeenCalledWith("/api/shutdown", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reattach: restartRequest }),
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
