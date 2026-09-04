import { afterEach, describe, expect, it, vi } from "vitest";
import { attachmentLifecycleApi } from "./attachment-lifecycle-api";
import type { Attachment } from "./contracts";

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
  cwd_git: null,
};

function response(body: unknown): Pick<Response, "ok" | "status" | "json"> {
  return { ok: true, status: 200, json: () => Promise.resolve(body) };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("attachmentLifecycleApi", () => {
  it("starts a stopped jack fresh, sending only the boundary fields that were given", async () => {
    const replacement = { ...attachment, id: "att-2", status: "starting", cli_session: null };
    const fetch = vi.fn().mockResolvedValue(response(replacement));
    vi.stubGlobal("fetch", fetch);

    await expect(attachmentLifecycleApi.fresh("att-1")).resolves.toEqual(replacement);
    expect(fetch).toHaveBeenLastCalledWith("/api/attachments/att-1/fresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });

    await attachmentLifecycleApi.fresh("att-1", {
      checkpoint: "docs/agent-checkpoints/book/task.md",
      after_message_id: 123,
    });
    expect(fetch).toHaveBeenLastCalledWith("/api/attachments/att-1/fresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ checkpoint: "docs/agent-checkpoints/book/task.md", after_message_id: 123 }),
    });
  });

  it("refuses a zero, negative, or fractional replay boundary before it reaches the server", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);

    // The contract is checked before any request is built, so this throws synchronously.
    expect(() => attachmentLifecycleApi.fresh("att-1", { after_message_id: -1 })).toThrow();
    expect(() => attachmentLifecycleApi.fresh("att-1", { after_message_id: 0 })).toThrow();
    expect(() => attachmentLifecycleApi.fresh("att-1", { after_message_id: 1.5 })).toThrow();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("forgets a stopped jack through its record endpoint, not the detach one", async () => {
    const fetch = vi.fn().mockResolvedValue(response({ ok: true }));
    vi.stubGlobal("fetch", fetch);

    await expect(attachmentLifecycleApi.forget("att-1")).resolves.toEqual({ ok: true });
    expect(fetch).toHaveBeenCalledWith("/api/attachments/att-1/record", { method: "DELETE" });
  });
});
