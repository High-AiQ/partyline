/** Who holds agent control of the shared screen, derived from `share.control`. */

import type { ScreenShare } from "./screen-contracts";

export interface ControlBadgeInfo {
  /** The agent granted control, or null when every agent on the line may act. */
  holder: string | null;
  /** The tooltip and accessible name. */
  label: string;
}

/**
 * The badge to draw, or null. Only an `active` grant counts: a pending
 * request is not control yet, and a revoked one (or no share at all) is over
 * the moment the server says so.
 *
 * `handle` asks about one process: a grant to another agent is not that
 * process's badge. A line-wide grant (`holder` null) names no process, so it
 * shows in the share status only.
 */
export function controlBadge(
  share: ScreenShare | null | undefined,
  handle?: string,
): ControlBadgeInfo | null {
  const control = share?.control;
  if (!share || control?.status !== "active") return null;
  if (handle !== undefined && control.holder !== handle) return null;
  const n = control.actions;
  const subject = control.holder ? `${control.holder} is controlling` : "Agents are controlling";
  return {
    holder: control.holder,
    label: `${handle !== undefined ? "Controlling" : subject} ${share.device_name} (${String(n)} action${n === 1 ? "" : "s"})`,
  };
}
