import { describe, expect, it } from "vitest";
import { taskModeInfo } from "./task-mode";

describe("task mode marker", () => {
  it("names each mode with its own tooltip and colour token", () => {
    const express = taskModeInfo({ task_status: "implementing", task_mode: "express" });
    const light = taskModeInfo({ task_status: "in_review", task_mode: "light" });
    const full = taskModeInfo({ task_status: "done", task_mode: "full" });
    expect(express?.tooltip).toBe("Express task: no review, no gates");
    expect(light?.tooltip).toContain("Light task");
    expect(full?.tooltip).toContain("Full task");
    expect(new Set([express?.tone, light?.tone, full?.tone]).size).toBe(3);
  });

  it("treats a task without a recorded mode as full and shows nothing for other lines", () => {
    expect(taskModeInfo({ task_status: "implementing" })?.mode).toBe("full");
    expect(taskModeInfo({ task_status: null, task_mode: null })).toBeNull();
    expect(taskModeInfo({})).toBeNull();
  });
});
