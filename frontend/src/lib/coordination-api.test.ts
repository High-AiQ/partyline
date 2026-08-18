import { afterEach, describe, expect, it, vi } from "vitest";
import { coordinationApi } from "./coordination-api";

function response(body: unknown): Pick<Response, "ok" | "status" | "json"> {
  return { ok: true, status: 200, json: vi.fn().mockResolvedValue(body) };
}

afterEach(() => vi.unstubAllGlobals());

describe("coordination api", () => {
  it("loads claims through their named boundary", async () => {
    const claims = [{ id: "claim-1", owner: "sol", paths: ["frontend/**"], created_at: 1, expires_at: 2 }];
    const fetch = vi.fn().mockResolvedValue(response(claims));
    vi.stubGlobal("fetch", fetch);

    await expect(coordinationApi.claims("conv-1")).resolves.toEqual(claims);
    expect(fetch).toHaveBeenCalledWith("/api/conversations/conv-1/claims", { method: "GET" });
  });

  it("creates and updates tasks with explicit JSON payloads", async () => {
    const task = {
      id: 1,
      body: "prove the badge",
      status: "open" as const,
      owner: "sol",
      created_at: 1,
      updated_at: 1,
    };
    const fetch = vi.fn().mockResolvedValue(response(task));
    vi.stubGlobal("fetch", fetch);

    await coordinationApi.createTask("conv-1", { body: task.body, owner: task.owner });
    expect(fetch).toHaveBeenLastCalledWith("/api/conversations/conv-1/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: task.body, owner: task.owner }),
    });

    await coordinationApi.updateTask(task.id, { status: "done" });
    expect(fetch).toHaveBeenLastCalledWith("/api/tasks/1", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "done" }),
    });
  });
});
