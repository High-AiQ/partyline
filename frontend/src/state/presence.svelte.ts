/** Ephemeral server-owned process activity shown on jack cards. */

import { SvelteSet } from "svelte/reactivity";
import type { WorkingEvent } from "../lib/contracts";

class Presence {
  working = new SvelteSet<string>();

  apply(event: WorkingEvent): void {
    if (event.working) this.working.add(event.attachment_id);
    else this.working.delete(event.attachment_id);
  }

  clear(): void {
    this.working.clear();
  }

  replace(attachmentIds: readonly string[]): void {
    this.working.clear();
    for (const id of attachmentIds) this.working.add(id);
  }
}

// Room is the sole writer: snapshots must pass its epoch guard before reaching this singleton.
export const presence = new Presence();
