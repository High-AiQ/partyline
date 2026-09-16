/** Light/dark theme: an explicit choice persists; otherwise the system preference wins live. */

import { readStoredTheme, resolveTheme, storeTheme } from "../lib/theme.js";
import type { Theme } from "../lib/theme.js";

const LIGHT_QUERY = "(prefers-color-scheme: light)";

function noopTeardown(): void {
  // No live media query to unsubscribe from.
}

function systemPrefersLight(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(LIGHT_QUERY).matches;
}

export class ThemeStore {
  current = $state<Theme>(resolveTheme(readStoredTheme(), systemPrefersLight()));
  /** True once a choice has been saved — from then on, the system preference no longer applies. */
  private explicit = readStoredTheme() !== null;

  constructor() {
    if (this.explicit) this.apply();
  }

  /**
   * Reflect an explicit choice on the document root.
   *
   * While nothing has been chosen, `data-theme` stays absent on purpose: the
   * `prefers-color-scheme` rule in `app.css` already renders the right theme
   * before this module even runs, and setting an attribute here first would
   * cost every unset visitor a flash of the wrong theme.
   */
  private apply(): void {
    if (typeof document === "undefined") return;
    document.documentElement.dataset.theme = this.current;
  }

  set(theme: Theme): void {
    this.explicit = true;
    this.current = theme;
    storeTheme(theme);
    this.apply();
  }

  toggle(): void {
    this.set(this.current === "dark" ? "light" : "dark");
  }

  /** Track the system preference live for as long as no explicit choice has been made. */
  watch(): () => void {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return noopTeardown;
    const query = window.matchMedia(LIGHT_QUERY);
    const sync = (): void => {
      if (this.explicit) return;
      this.current = query.matches ? "light" : "dark";
    };
    query.addEventListener("change", sync);
    return () => {
      query.removeEventListener("change", sync);
    };
  }
}

export const theme = new ThemeStore();
