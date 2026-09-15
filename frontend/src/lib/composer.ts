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
