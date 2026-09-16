/** Pure light/dark theme rules: storage keys, validation, and resolution. */

import { z } from "zod";

export const ThemeSchema = z.enum(["light", "dark"]);
export type Theme = z.infer<typeof ThemeSchema>;

export const THEME_STORAGE_KEY = "partyline_theme";

/** A valid saved choice wins; anything missing or invalid falls back to the system preference. */
export function resolveTheme(stored: unknown, systemPrefersLight: boolean): Theme {
  const parsed = ThemeSchema.safeParse(stored);
  if (parsed.success) return parsed.data;
  return systemPrefersLight ? "light" : "dark";
}

/** `null` for anything missing, invalid, or unreadable — never throws. */
export function readStoredTheme(): Theme | null {
  try {
    const parsed = ThemeSchema.safeParse(localStorage.getItem(THEME_STORAGE_KEY));
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

/** Best-effort: a blocked or full storage area must not stop the toggle from working. */
export function storeTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage may be unavailable (private mode, quota) — the in-memory theme still applies.
  }
}
