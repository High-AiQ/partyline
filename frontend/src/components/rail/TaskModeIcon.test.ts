import { mount, unmount, type ComponentProps } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import TaskModeIcon from "./TaskModeIcon.svelte";

afterEach(() => {
  document.body.replaceChildren();
});

function icon(props: ComponentProps<typeof TaskModeIcon>) {
  const component = mount(TaskModeIcon, { target: document.body, props });
  const marker = document.querySelector(".task-mode");
  return { marker, stop: () => unmount(component) };
}

describe("task mode icon", () => {
  it.each([
    ["express", "Express task: no review, no gates", "text-copper"],
    ["light", "Light task: review, gates scale with the diff", "text-green"],
    ["full", "Full task: review and every gate", "text-sky"],
  ] as const)("renders the %s marker with its tooltip label", async (mode, label, tone) => {
    const { marker, stop } = icon({ line: { task_status: "implementing", task_mode: mode } });
    try {
      expect(marker?.getAttribute("aria-label")).toBe(label);
      expect(marker?.classList.contains(`task-mode-${mode}`)).toBe(true);
      expect(marker?.classList.contains(tone)).toBe(true);
      expect(marker?.querySelector("svg path")?.tagName).toBe("path");
    } finally {
      await stop();
    }
  });

  it("draws a different glyph per mode", async () => {
    const shapes: string[] = [];
    for (const mode of ["express", "light", "full"] as const) {
      const { marker, stop } = icon({ line: { task_status: "done", task_mode: mode } });
      shapes.push(marker?.querySelector("path")?.getAttribute("d") ?? "");
      await stop();
    }
    expect(new Set(shapes).size).toBe(3);
  });

  it("shows nothing for a line that is not a task", async () => {
    const { marker, stop } = icon({ line: { task_status: null } });
    try {
      expect(marker).toBeNull();
    } finally {
      await stop();
    }
  });
});
