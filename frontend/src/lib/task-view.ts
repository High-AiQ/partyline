/** Split a task body into its summary line and its done-when expectation. */

import type { Task } from "./contracts";

export interface TaskView {
  /** The actionable summary: everything before a Done-when line. */
  summary: string;
  /** The expectation, verbatim, when the body carries one. */
  doneWhen: string | null;
  /** Short owner chip, or null when unassigned. */
  owner: string | null;
}

/**
 * The line's convention, established 2026-08-19: an open task's body may end
 * with a `Done when:` line stating the completion expectation. Agents write
 * it; the drawer surfaces it so a human never expands a row to find it.
 *
 * Matching is on the first line that starts with the marker (case-insensitive,
 * colon optional) — not a grep for the words anywhere, so a summary that
 * merely mentions "done" is never misread as carrying an expectation.
 */
const DONE_WHEN = /^\s*done\s+when\b\s*:?\s*/i;

export function taskView(task: Pick<Task, "body" | "owner">): TaskView {
  const lines = task.body.split("\n");
  const marker = lines.findIndex((line) => DONE_WHEN.test(line));
  if (marker === -1) {
    return { summary: task.body.trim(), doneWhen: null, owner: task.owner ?? null };
  }
  const doneWhen = lines.slice(marker).join("\n").replace(DONE_WHEN, "").trim();
  return {
    summary: lines.slice(0, marker).join("\n").trim(),
    doneWhen: doneWhen || null,
    owner: task.owner ?? null,
  };
}
