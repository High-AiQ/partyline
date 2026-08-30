/** Lazy, explicitly allowlisted code highlighting for sanitized message nodes. */

import type { LanguageFn } from "highlight.js";
import {
  byteLength,
  CODE_BLOCK_MAX_BYTES,
  normalizeCodeLanguage,
  type CodeLanguage,
} from "./markdown-contract";

interface HighlightEngine {
  registerLanguage(name: string, language: LanguageFn): void;
  highlight(code: string, options: { language: string; ignoreIllegals: boolean }): { value: string };
}
type CoreLoader = () => Promise<HighlightEngine>;
type LanguageLoader = () => Promise<LanguageFn>;
export type EnhancementGuard = () => boolean;

const languageLoaders: Readonly<Record<CodeLanguage, LanguageLoader>> = {
  plaintext: () => import("highlight.js/lib/languages/plaintext").then((module) => module.default),
  bash: () => import("highlight.js/lib/languages/bash").then((module) => module.default),
  javascript: () => import("highlight.js/lib/languages/javascript").then((module) => module.default),
  typescript: () => import("highlight.js/lib/languages/typescript").then((module) => module.default),
  json: () => import("highlight.js/lib/languages/json").then((module) => module.default),
  python: () => import("highlight.js/lib/languages/python").then((module) => module.default),
  xml: () => import("highlight.js/lib/languages/xml").then((module) => module.default),
  css: () => import("highlight.js/lib/languages/css").then((module) => module.default),
  sql: () => import("highlight.js/lib/languages/sql").then((module) => module.default),
  diff: () => import("highlight.js/lib/languages/diff").then((module) => module.default),
};

const defaultCoreLoader: CoreLoader = () =>
  Promise.all([import("highlight.js/lib/core"), import("../styles/highlight-theme.css")]).then(
    ([module]) => module.default,
  );

let coreLoader = defaultCoreLoader;
let languageLoaderOverrides: Partial<Readonly<Record<CodeLanguage, LanguageLoader>>> = {};
let corePromise: Promise<HighlightEngine> | null = null;
const languagePromises = new Map<string, Promise<LanguageFn>>();
const registeredLanguages = new Set<string>();

function loadCore(): Promise<HighlightEngine> {
  corePromise ??= coreLoader();
  return corePromise;
}

function loadLanguage(language: CodeLanguage): Promise<LanguageFn> {
  const loader = languageLoaderOverrides[language] ?? languageLoaders[language];
  const existing = languagePromises.get(language);
  if (existing) return existing;
  const promise = loader();
  languagePromises.set(language, promise);
  return promise;
}

async function highlightNode(node: HTMLElement, isCurrent: EnhancementGuard): Promise<void> {
  if (node.dataset.codeHighlighted === "true") return;
  const marker = node.getAttribute("data-code-language");
  const language = marker ? normalizeCodeLanguage(marker) : null;
  const source = node.textContent;
  if (!language || language !== marker || byteLength(source) > CODE_BLOCK_MAX_BYTES) return;

  const languagePromise = loadLanguage(language);
  try {
    const [engine, grammar] = await Promise.all([loadCore(), languagePromise]);
    if (!isCurrent()) return;
    if (!registeredLanguages.has(language)) {
      engine.registerLanguage(language, grammar);
      registeredLanguages.add(language);
    }
    node.innerHTML = engine.highlight(source, { language, ignoreIllegals: true }).value;
    node.classList.add("hljs");
    node.dataset.codeHighlighted = "true";
  } catch (error: unknown) {
    console.warn("Failed to highlight code block:", error);
  }
}

export async function enhanceCode(
  root: HTMLElement,
  isCurrent: EnhancementGuard = () => true,
): Promise<void> {
  const nodes = [...root.querySelectorAll<HTMLElement>("code[data-code-language]")];
  await Promise.all(nodes.map((node) => highlightNode(node, isCurrent)));
}

interface HighlightLoaderOverrides {
  core?: CoreLoader;
  languages?: Partial<Readonly<Record<CodeLanguage, LanguageLoader>>>;
}

/** Reset module caches and optionally substitute deterministic loaders in tests. */
export function _setHighlightLoadersForTest(overrides: HighlightLoaderOverrides = {}): void {
  coreLoader = overrides.core ?? defaultCoreLoader;
  languageLoaderOverrides = overrides.languages ?? {};
  corePromise = null;
  languagePromises.clear();
  registeredLanguages.clear();
}
