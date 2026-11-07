/**
 * Deep links into settings: `#/settings` and `#/settings/<section>`.
 *
 * A hash route like a line's (`#/c/<id>`), so a refresh, Back and Forward work
 * without the server learning client routes. A settings route sits *over* the
 * open line: it never means "leave the line".
 */

export const SECTION_IDS = [
  "general",
  "appearance",
  "voice",
  "processes",
  "resources",
  "storage",
  "computers",
  "advanced",
  "about",
] as const;
export type SectionId = (typeof SECTION_IDS)[number];
export const DEFAULT_SECTION: SectionId = "general";

const ROUTE = /^#\/settings(?:\/([^/?#]*))?\/?$/;

export function isSectionId(value: string): value is SectionId {
  return (SECTION_IDS as readonly string[]).includes(value);
}

/** True for any settings hash, including one naming a section that does not exist. */
export function isSettingsRoute(hash: string): boolean {
  return ROUTE.test(hash);
}

/** The section a hash names; an unknown or missing section is the default one; null off settings. */
export function parseSettingsRoute(hash: string): SectionId | null {
  const match = ROUTE.exec(hash);
  if (!match) return null;
  const section = (match[1] ?? "").toLowerCase();
  return isSectionId(section) ? section : DEFAULT_SECTION;
}

export const settingsRoute = (section: SectionId): string => `#/settings/${section}`;
