import { afterEach, describe, expect, it, vi } from "vitest";
import { writeSetApi } from "../lib/write-set-api";
import type { WriteSetGrantRequest } from "../lib/write-set-contracts";
import { WriteSetState } from "./write-set.svelte.js";

describe("write-set banner state", () => {
  afterEach(() => vi.restoreAllMocks());

  it("clears the old line and preserves a request event over delayed responses", async () => {
    let resolveA: ((value: { request: WriteSetGrantRequest | null }) => void) | undefined;
    let resolveB: ((value: { request: WriteSetGrantRequest | null }) => void) | undefined;
    const pending = vi.spyOn(writeSetApi, "pending").mockImplementation((convId) => {
      if (convId === "A") return new Promise((resolve) => (resolveA = resolve));
      return new Promise((resolve) => (resolveB = resolve));
    });
    const state = new WriteSetState();
    const loadingA = state.load("A");
    state.activate("B");

    expect(state.request).toBeNull();
    const loadingB = state.load("B");
    const event: WriteSetGrantRequest = {
      id: "request-B",
      conversation_id: "B",
      requester: "worker",
      path: "/tmp/B",
      created_at: 1,
    };
    state.apply(event);
    resolveA?.({ request: { ...event, id: "stale-A", conversation_id: "A" } });
    resolveB?.({ request: null });
    await loadingA;
    await loadingB;

    expect(state.request).toEqual(event);
    expect(pending).toHaveBeenCalledTimes(2);
  });
});
