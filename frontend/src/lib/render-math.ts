/**
 * Lazy math renderer using KaTeX.
 *
 * Scans DOM elements for math placeholders emitted by markdown rendering
 * (`[data-math="inline"]` and `[data-math="display"]`) and asynchronously
 * enhances them with KaTeX without blocking the initial message feed.
 */

import type katexType from "katex";
import { byteLength, MATH_MAX_EXPRESSION_BYTES, MATH_MAX_EXPRESSIONS_PER_MESSAGE } from "./markdown-contract";

export const MAX_EXPRESSION_BYTES = MATH_MAX_EXPRESSION_BYTES;
export const MAX_EXPRESSIONS_PER_MESSAGE = MATH_MAX_EXPRESSIONS_PER_MESSAGE;

export interface MathRenderOptions {
  displayMode: boolean;
  throwOnError: boolean;
  strict: "warn";
  trust: boolean;
  output: "htmlAndMathml";
  macros: Record<string, string>;
}

let katexLoaderPromise: Promise<typeof katexType> | null = null;
let customLoaderForTest: (() => Promise<typeof katexType>) | null = null;

/**
 * Dynamically import KaTeX and its CSS, memoizing the in-flight/resolved/rejected promise.
 *
 * Rejection remains permanently memoized so failed network imports do not retry
 * in a hot loop on subsequent messages.
 */
export async function loadKatex(): Promise<typeof katexType> {
  if (!katexLoaderPromise) {
    if (customLoaderForTest) {
      katexLoaderPromise = customLoaderForTest();
    } else {
      katexLoaderPromise = Promise.all([import("katex"), import("katex/dist/katex.min.css")]).then(
        ([mod]) => {
          // Handle both ESM default and namespace exports
          const katex = (mod as { default?: typeof katexType }).default ?? mod;
          return katex;
        },
      );
    }
  }
  return katexLoaderPromise;
}

/** Override or reset the loader cache for testing error and retry scenarios. */
export function _setKatexLoaderForTest(loader: (() => Promise<typeof katexType>) | null = null): void {
  customLoaderForTest = loader;
  katexLoaderPromise = null;
}

/**
 * Enhance math placeholder elements within a given root container.
 *
 * Safe and idempotent: already rendered nodes are skipped, failed imports or
 * over-limit expressions leave the raw TeX source intact.
 */
export async function enhanceMath(root: HTMLElement, isCurrent: () => boolean = () => true): Promise<void> {
  const elements = root.querySelectorAll<HTMLElement>("[data-math]");
  if (elements.length === 0) return;

  let katex: typeof katexType;
  try {
    katex = await loadKatex();
  } catch (error: unknown) {
    // If loading KaTeX fails (e.g. offline/network issue), leave raw source visible.
    console.warn("Failed to load KaTeX for math rendering:", error);
    return;
  }
  if (!isCurrent()) return;

  // Cap the number of expressions processed per message
  const toProcess = Array.from(elements).slice(0, MAX_EXPRESSIONS_PER_MESSAGE);

  for (const el of toProcess) {
    if (!isCurrent()) return;
    if (el.dataset.mathRendered === "true") continue;

    const mode = el.getAttribute("data-math");
    if (mode !== "inline" && mode !== "display") continue;

    const source = el.textContent;
    // Check expression size limit
    if (byteLength(source) > MAX_EXPRESSION_BYTES) {
      continue;
    }

    try {
      const displayMode = mode === "display";
      const options: MathRenderOptions = {
        displayMode,
        throwOnError: false,
        strict: "warn",
        trust: false,
        output: "htmlAndMathml",
        macros: {},
      };
      katex.render(source, el, options);
      el.dataset.mathRendered = "true";
    } catch (error: unknown) {
      console.warn("KaTeX render failure on expression:", error);
      el.textContent = source;
    }
  }
}
