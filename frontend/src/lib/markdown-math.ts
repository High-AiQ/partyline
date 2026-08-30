import { Marked, type TokenizerAndRendererExtension } from "marked";
import { byteLength, MATH_MAX_EXPRESSION_BYTES, MATH_MAX_EXPRESSIONS_PER_MESSAGE } from "./markdown-contract";

function backslashesBefore(source: string, index: number): number {
  let count = 0;
  for (let cursor = index - 1; cursor >= 0 && source[cursor] === "\\"; cursor -= 1) count += 1;
  return count;
}

function mathWithinLimit(text: string, budget: { count: number }): boolean {
  if (budget.count >= MATH_MAX_EXPRESSIONS_PER_MESSAGE) return false;
  if (byteLength(text) > MATH_MAX_EXPRESSION_BYTES) return false;
  budget.count += 1;
  return true;
}

function displayMathExtension(
  name: string,
  open: string,
  close: string,
  budget: { count: number },
): TokenizerAndRendererExtension {
  return {
    name,
    level: "block",
    start(src) {
      return src.startsWith(open) ? 0 : undefined;
    },
    tokenizer(src) {
      if (!src.startsWith(open)) return;
      const end = src.indexOf(close, open.length);
      if (end === -1) return;
      const text = src.slice(open.length, end);
      if (!mathWithinLimit(text, budget)) return;
      return { type: name, raw: src.slice(0, end + close.length), text };
    },
    renderer(token) {
      return `<span data-math="display">${String(token.text)}</span>`;
    },
  };
}

export function mathExtensions(budget: { count: number }): TokenizerAndRendererExtension[] {
  return [
    displayMathExtension("math_display_bracket", "\\[", "\\]", budget),
    displayMathExtension("math_display_dollar", "$$", "$$", budget),
    {
      name: "math_inline",
      level: "inline",
      start(src) {
        if (!src.startsWith("\\(")) return;
        return backslashesBefore(src, 1) % 2 === 1 ? 0 : undefined;
      },
      tokenizer(src) {
        if (!src.startsWith("\\(") || backslashesBefore(src, 1) % 2 !== 1) return;
        const close = src.indexOf("\\)");
        if (close === -1) return;
        const text = src.slice(2, close);
        if (text.includes("\n") || !mathWithinLimit(text, budget)) return;
        return { type: "math_inline", raw: src.slice(0, close + 2), text };
      },
      renderer(token) {
        return `<span data-math="inline">${String(token.text)}</span>`;
      },
    },
  ];
}

export function createRichMarked(renderer: Record<string, unknown>): Marked {
  const budget = { count: 0 };
  return new Marked({
    gfm: true,
    breaks: false,
    renderer,
    extensions: mathExtensions(budget),
  });
}
