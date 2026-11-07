/**
 * Which settings tab is showing, read from the URL.
 *
 * The hash is the source of truth: the tabs are real links to
 * `#/settings/<section>`, so a deep link opens the settings modal on that tab
 * and Back and Forward move between tabs and out of settings like any page.
 * `SettingsRoute` opens and closes the modal to match `section`. Opening
 * remembers the line route it covered so closing returns there.
 */
import { DEFAULT_SECTION, parseSettingsRoute, settingsRoute } from "../lib/settings-route";
import type { SectionId } from "../lib/settings-route";

const currentHash = (): string => (typeof location === "undefined" ? "" : location.hash);
const go = (hash: string): void => {
  history.pushState({}, "", location.pathname + location.search + hash);
};

class SettingsNav {
  section = $state<SectionId | null>(parseSettingsRoute(currentHash()));
  /** A setting row to scroll to and focus once its tab has rendered. */
  focusTarget = $state<string | null>(null);
  #returnTo = "";

  /** Re-read the URL after a hashchange (a tab link, Back or Forward). */
  sync(): void {
    const next = parseSettingsRoute(currentHash());
    // Arriving by URL there is no line route of ours to go back to.
    if (this.section === null && next !== null) this.#returnTo = "";
    this.section = next;
    if (next === null) this.focusTarget = null;
  }

  show(section: SectionId = DEFAULT_SECTION, focus: string | null = null): void {
    if (this.section === null) this.#returnTo = parseSettingsRoute(currentHash()) ? "" : currentHash();
    const hash = settingsRoute(section);
    if (currentHash() !== hash) go(hash);
    this.section = section;
    this.focusTarget = focus;
  }

  /** The modal went away (close button, Escape, backdrop): leave the settings route too. */
  close(): void {
    if (this.section === null) return;
    this.section = null;
    this.focusTarget = null;
    if (parseSettingsRoute(currentHash())) go(this.#returnTo);
  }
}

export const settingsNav = new SettingsNav();
