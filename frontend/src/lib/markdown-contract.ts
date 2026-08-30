/** Shared math/code marker contract for the renderer and process briefing. */

export const MATH_DELIMITER_CONTRACT = {
  inline: ["\\(", "\\)"] as const,
  display: [["\\[", "\\]"] as const, ["$$", "$$"] as const],
} as const;

export const MATH_MAX_EXPRESSION_BYTES = 20 * 1024;
export const MATH_MAX_EXPRESSIONS_PER_MESSAGE = 50;
export const CODE_BLOCK_MAX_BYTES = 50 * 1024;

export const CODE_LANGUAGES = [
  "plaintext",
  "bash",
  "javascript",
  "typescript",
  "json",
  "python",
  "xml",
  "css",
  "sql",
  "diff",
] as const;
export type CodeLanguage = (typeof CODE_LANGUAGES)[number];

/** highlight.js canonical ids the enhancer may load. */
export const CODE_LANGUAGE_ALIASES: Readonly<Record<string, CodeLanguage>> = {
  plaintext: "plaintext",
  text: "plaintext",
  bash: "bash",
  sh: "bash",
  shell: "bash",
  javascript: "javascript",
  js: "javascript",
  typescript: "typescript",
  ts: "typescript",
  json: "json",
  python: "python",
  py: "python",
  xml: "xml",
  html: "xml",
  css: "css",
  sql: "sql",
  diff: "diff",
  patch: "diff",
};

export const SUPPORTED_CODE_LANGUAGES: ReadonlySet<string> = new Set(CODE_LANGUAGES);

const LANG_TOKEN = /^[a-z0-9+#.-]+/;

export const byteLength = (text: string): number => new TextEncoder().encode(text).length;

/** Only canonical renderer-controlled ids survive onto the DOM. */
export function normalizeCodeLanguage(raw: string): CodeLanguage | null {
  const token = LANG_TOKEN.exec(raw.trim().toLowerCase())?.[0]?.slice(0, 32) ?? "";
  if (!token) return null;
  return CODE_LANGUAGE_ALIASES[token] ?? null;
}
