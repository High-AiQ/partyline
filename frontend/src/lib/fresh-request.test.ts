import { describe, expect, it } from "vitest";
import { buildFreshRequest } from "./fresh-request";

describe("buildFreshRequest", () => {
  it("makes a blank fresh start when nothing was typed", () => {
    expect(buildFreshRequest("", "  ")).toEqual({ ok: true, request: {} });
  });

  it("sends a checkpoint alone when no boundary was given", () => {
    expect(buildFreshRequest("  docs/agent-checkpoints/book/task.md ", "")).toEqual({
      ok: true,
      request: { checkpoint: "docs/agent-checkpoints/book/task.md" },
    });
  });

  it("sends the checkpoint with its boundary", () => {
    expect(buildFreshRequest("ckpt.md", " 123 ")).toEqual({
      ok: true,
      request: { checkpoint: "ckpt.md", after_message_id: 123 },
    });
  });

  it("refuses zero, which would replay the whole line", () => {
    expect(buildFreshRequest("ckpt.md", "0")).toEqual({
      ok: false,
      error: "the message id must be a positive whole number",
    });
  });

  it("refuses a boundary without a checkpoint, as the server does", () => {
    expect(buildFreshRequest("", "123")).toEqual({
      ok: false,
      error: "a replay boundary needs a checkpoint to replay from",
    });
  });

  it("refuses a boundary that is not a whole number", () => {
    expect(buildFreshRequest("ckpt.md", "12a")).toMatchObject({ ok: false });
    expect(buildFreshRequest("ckpt.md", "-1")).toMatchObject({ ok: false });
    expect(buildFreshRequest("ckpt.md", "1.5")).toMatchObject({ ok: false });
  });

  it("refuses a boundary JSON cannot carry exactly", () => {
    expect(buildFreshRequest("ckpt.md", String(Number.MAX_SAFE_INTEGER))).toMatchObject({ ok: true });
    expect(buildFreshRequest("ckpt.md", "9007199254740993")).toMatchObject({ ok: false });
    expect(buildFreshRequest("ckpt.md", "1e3")).toMatchObject({ ok: false });
  });
});
