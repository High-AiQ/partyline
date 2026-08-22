/** Ephemeral server-owned process activity shown on jack cards. */

import { SvelteMap } from "svelte/reactivity";
import type { PresenceCompletion, PresencePhase, PresenceState, WorkingEvent } from "../lib/contracts";

export interface PresenceEntry {
  phase: PresencePhase;
  completion: PresenceCompletion;
  /** Server epoch seconds of the last transition this attachment announced. */
  since: number;
  /** Turn metadata for receipt pairing; informational to the client. */
  turn: number;
  /** Rises on every server announce, ordering transitions within a turn. */
  revision: number;
  /** Boolean-only presence from a pre-phase server: render today's look, never decay. */
  legacy: boolean;
  /** Number of mention wakes queued mid-turn. */
  held: number;
}

const LEGACY_ENTRY: Omit<PresenceEntry, "phase"> = {
  completion: "none",
  since: 0,
  turn: 0,
  revision: 0,
  legacy: true,
  held: 0,
};

function entryFromEvent(event: WorkingEvent): PresenceEntry {
  if (event.phase === undefined) {
    return { ...LEGACY_ENTRY, phase: event.working ? "working" : "idle" };
  }
  // The wire normalizer stamps a legacy boolean frame with zero since and
  // revision; a modern announce always carries a real epoch and revision ≥ 1.
  const legacy = (event.since ?? 0) === 0 && (event.revision ?? 0) === 0;
  return {
    phase: event.phase,
    completion: event.completion ?? "none",
    since: event.since ?? 0,
    turn: event.turn ?? 0,
    revision: event.revision ?? 0,
    legacy,
    held: event.held ?? 0,
  };
}

class Presence {
  /**
   * Includes idle and quiet tombstones: their revisions guard against a
   * buffered pre-snapshot event resurrecting an attachment the server
   * already reported done.
   */
  entries = new SvelteMap<string, PresenceEntry>();

  apply(event: WorkingEvent): void {
    const held = this.entries.get(event.attachment_id);
    const next = entryFromEvent(event);
    // A modern server bumps the revision on every announce, so strictly older
    // means late or reordered. Equal revisions only arise from legacy frames,
    // which carry no ordering at all and must pass through untouched.
    if (held && next.revision < held.revision) return;
    this.entries.set(event.attachment_id, next);
  }

  clear(): void {
    this.entries.clear();
  }

  /** Atomically adopt a revisioned snapshot, tombstones included. */
  replace(states: readonly PresenceState[]): void {
    this.entries.clear();
    for (const state of states) {
      this.entries.set(state.id, { ...state, legacy: false });
    }
  }

  /** Adopt a pre-phase server's boolean snapshot: all busy, no decay. */
  replaceLegacy(attachmentIds: readonly string[]): void {
    this.entries.clear();
    for (const id of attachmentIds) this.entries.set(id, { ...LEGACY_ENTRY, phase: "working" });
  }
}

// Room is the sole writer: snapshots must pass its epoch guard before reaching
// this singleton.
export const presence = new Presence();
