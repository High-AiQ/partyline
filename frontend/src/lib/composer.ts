/** Pure text-editing rules for the message composer. */

export interface TextEdit {
  value: string;
  caret: number;
}

const LONG_PLACEHOLDER = "say something… @name to ring an agent";

/** Keep the composer prompt to one line on the narrow layout. */
export function composerPlaceholder(narrow: boolean): string {
  return narrow ? "say something…" : LONG_PLACEHOLDER;
}

/** Replace the selected range with a newline and put the caret after it. */
export function insertNewline(value: string, start: number, end: number): TextEdit {
  const next = value.slice(0, start) + "\n" + value.slice(end);
  return { value: next, caret: start + 1 };
}

/** Mirrors the server's `MAX_MESSAGE_BODY` (partyline/hierarchy_contracts.py). */
export const MAX_MESSAGE_BODY = 10_000;
/** The counter stays out of the way until a draft is long enough to matter. */
export const COUNTER_FROM = 1_000;
/** Within a tenth of the limit the counter turns to a warning colour. */
export const COUNTER_WARN_FROM = 9_000;

/** Cut a draft to the message cap without leaving half of an emoji behind. */
export function clampDraft(value: string): string {
  if (value.length <= MAX_MESSAGE_BODY) return value;
  const cut = value.slice(0, MAX_MESSAGE_BODY);
  return /[\ud800-\udbff]$/.test(cut) ? cut.slice(0, -1) : cut;
}
