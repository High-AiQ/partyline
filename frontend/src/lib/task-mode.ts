import type { Conversation } from "./contracts";

export type TaskMode = NonNullable<Conversation["task_mode"]>;

export interface TaskModeInfo {
  mode: TaskMode;
  /** Name shown beside the icon for assistive tech. */
  label: string;
  /** Tooltip text. */
  tooltip: string;
  /** Tailwind text-colour utility drawn from the theme tokens. */
  tone: string;
}

const MODES: Record<TaskMode, TaskModeInfo> = {
  express: {
    mode: "express",
    label: "Express task",
    tooltip: "Express task: no review, no gates",
    tone: "text-copper",
  },
  light: {
    mode: "light",
    label: "Light task",
    tooltip: "Light task: review, gates scale with the diff",
    tone: "text-green",
  },
  full: {
    mode: "full",
    label: "Full task",
    tooltip: "Full task: review and every gate",
    tone: "text-sky",
  },
};

/** The marker for a task line; a line that is not a task has none. */
export function taskModeInfo(line: Pick<Conversation, "task_status" | "task_mode">): TaskModeInfo | null {
  if (!line.task_status) return null;
  return MODES[line.task_mode ?? "full"];
}
