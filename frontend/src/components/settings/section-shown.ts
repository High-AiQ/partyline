/**
 * Which settings tab is on screen. The dialog keeps every opened tab mounted
 * so drafts survive a search or a tab switch; a hidden tab reads this to stop
 * anything live, such as a test recording.
 */
import { getContext, setContext } from "svelte";
import type { SectionId } from "../../lib/settings-route";
const SHOWN = Symbol("settings-section-shown");

/** The dialog says which tab is on screen; tabs stay mounted while hidden, to keep drafts. */
export function provideSectionShown(isShown: (_id: SectionId) => boolean): void {
  setContext(SHOWN, isShown);
}

/**
 * Whether this tab is on screen (always true outside the dialog). A hidden tab
 * keeps its drafts but must stop anything live, such as a test recording.
 */
export function sectionShown(id: SectionId): () => boolean {
  const isShown = getContext<((_id: SectionId) => boolean) | undefined>(SHOWN);
  return () => isShown?.(id) ?? true;
}
