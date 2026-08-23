/** Pure derivation of the working-badge treatment from a presence entry. */

import type { PresenceEntry } from "../state/presence.svelte.js";

/**
 * A guess must look like a guess: uncertainty rides three redundant channels
 * (label suffix, hollow dot, no pulse) so it survives colour-blindness and
 * monochrome. Timers may only reduce confidence here — never clear a badge
 * and never assert an end the server did not report.
 */
export interface BadgeTreatment {
  label: string;
  tone: "green" | "copper";
  dot: "filled" | "hollow";
  pulse: "live" | "slow" | "none";
  tooltip: string;
}

/** A `none` adapter shows today's confident look for this long before decaying. */
const CONFIDENT_SECONDS = 240;

function heldTooltip(held: number): string {
  return held > 0 ? `${String(held)} wake${held === 1 ? "" : "s"} held while working` : "";
}

function confident(speaking: boolean, held = 0): BadgeTreatment {
  return {
    label: "working…",
    tone: "green",
    dot: "filled",
    // speaking is display-only: the dot goes solid, the label stays "working…"
    pulse: speaking ? "none" : "live",
    tooltip: heldTooltip(held),
  };
}

function describe(seconds: number): string {
  return seconds < 90 ? `${String(Math.round(seconds))}s` : `${String(Math.round(seconds / 60))}m`;
}

export function badgeTreatment(entry: PresenceEntry | undefined, now: number): BadgeTreatment | null {
  if (!entry || entry.phase === "idle") return null;

  if (entry.phase === "quiet") {
    return {
      label: "done?",
      tone: "green",
      dot: "hollow",
      pulse: "none",
      tooltip: "guessed idle from inactivity — this CLI sends no turn-end signal",
    };
  }

  // Legacy boolean presence carries no phases or revisions; it must render
  // exactly what it always rendered, and decay would be a claim we cannot make.
  if (entry.legacy) return confident(entry.phase === "speaking", entry.held);

  const age = Math.max(0, now - entry.since);

  if (entry.completion === "receipt") {
    // An open receipt turn is the server's word. Age is not evidence the
    // process stalled: grok's thinking turns are silent for tens of minutes,
    // and the old 10-minute guess labelled them `stalled?` while they worked.
    return confident(entry.phase === "speaking", entry.held);
  }

  if (age >= CONFIDENT_SECONDS) {
    const held = heldTooltip(entry.held);
    return {
      // The label never stops saying working; only the confident channels dim.
      label: "working…",
      tone: "green",
      dot: "hollow",
      pulse: "none",
      tooltip: [`no turn-end signal from this CLI · active for ${describe(age)}`, held]
        .filter(Boolean)
        .join(" · "),
    };
  }
  return confident(entry.phase === "speaking", entry.held);
}
