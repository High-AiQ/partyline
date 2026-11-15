import { describe, expect, it } from "vitest";
import { taskModeInfo } from "./task-mode";
import { ConversationSchema } from "./conversation-contracts";

describe("task mode marker", () => {
  it("names each mode with its own tooltip and colour token", () => {
    const express = taskModeInfo({ task_status: "implementing", task_mode: "express" });
    const light = taskModeInfo({ task_status: "in_review", task_mode: "suite" });
    const full = taskModeInfo({ task_status: "done", task_mode: "full" });
    expect(express?.tooltip).toBe("Express task: no review, no gates");
    expect(light?.tooltip).toContain("Suite run");
    expect(full?.tooltip).toContain("Full task");
    expect(new Set([express?.tone, light?.tone, full?.tone]).size).toBe(3);
  });

  it("normalizes legacy light rows to full while accepting suite rows", () => {
    const base = { id: "task", name: "Task", topic: "", created_at: 1, task_status: "in_review" };
    expect(ConversationSchema.parse({ ...base, task_mode: "light" }).task_mode).toBe("full");
    expect(ConversationSchema.parse({ ...base, task_mode: "suite" }).task_mode).toBe("suite");
  });

  it("treats a task without a recorded mode as full and shows nothing for other lines", () => {
    expect(taskModeInfo({ task_status: "implementing" })?.mode).toBe("full");
    expect(taskModeInfo({ task_status: null, task_mode: null })).toBeNull();
    expect(taskModeInfo({})).toBeNull();
  });
});
