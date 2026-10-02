/** Lazy, explicitly allowlisted code highlighting for sanitized message nodes. */

import type { LanguageFn } from "highlight.js";
import { copyText } from "./clipboard";
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

function codeCopyButton(pre: HTMLElement, code: HTMLElement): void {
  if (pre.parentElement?.classList.contains("code-block-shell")) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "code-copy";
  button.setAttribute("aria-label", "copy code block");
  button.dataset.copyUi = "true";
  button.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15V5a2 2 0 0 1 2-2h10"></path></svg>';
  const status = document.createElement("span");
  status.className = "code-copy-status sr-only";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.dataset.copyUi = "true";
  let revert: ReturnType<typeof setTimeout> | undefined;
  const copyCode = async (): Promise<void> => {
    let source = code.textContent;
    try {
      source = decodeURIComponent(code.getAttribute("data-code-source") ?? encodeURIComponent(source));
    } catch {
      // If the marker is malformed, the unhighlighted text remains safe to copy.
    }
    const success = await copyText(source);
    status.textContent = success ? "copied" : "copy failed: clipboard unavailable";
    button.setAttribute("aria-label", success ? "copied" : "copy failed");
    button.title = success ? "Copied" : "Could not copy: clipboard unavailable";
    button.innerHTML = success
      ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 13 4 4L19 7"></path></svg>'
      : '<span aria-hidden="true">!</span>';
    clearTimeout(revert);
    if (success) {
      revert = setTimeout(() => {
        status.textContent = "";
        button.setAttribute("aria-label", "copy code block");
        button.removeAttribute("title");
        button.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15V5a2 2 0 0 1 2-2h10"></path></svg>';
      }, 1500);
    }
  };
  button.addEventListener("click", () => {
    void copyCode();
  });
  const shell = document.createElement("div");
  shell.className = "code-block-shell";
  const parent = pre.parentElement;
  if (!parent) return;
  parent.insertBefore(shell, pre);
  shell.append(pre, button, status);
}

export async function enhanceCode(
  root: HTMLElement,
  isCurrent: EnhancementGuard = () => true,
): Promise<void> {
  const nodes = [...new Set(root.querySelectorAll<HTMLElement>("pre > code, code[data-code-language]"))];
  await Promise.all(nodes.map((node) => highlightNode(node, isCurrent)));
  if (!isCurrent()) return;
  for (const code of nodes) {
    const pre = code.parentElement;
    if (pre?.tagName === "PRE") codeCopyButton(pre, code);
  }
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
