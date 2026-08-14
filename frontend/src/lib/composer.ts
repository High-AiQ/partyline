/** Pure text-editing rules for the message composer. */

export interface TextEdit {
  value: string;
  caret: number;
}

/** Replace the selected range with a newline and put the caret after it. */
export function insertNewline(value: string, start: number, end: number): TextEdit {
  const next = value.slice(0, start) + "\n" + value.slice(end);
  return { value: next, caret: start + 1 };
}
