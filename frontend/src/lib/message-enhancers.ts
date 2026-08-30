/** Tiny main-chunk registry for optional message renderers. */

import type { Action } from "svelte/action";
import type { EnhancementGuard } from "./highlight-code";

interface CodeEnhancerModule {
  enhanceCode(root: HTMLElement, isCurrent: EnhancementGuard): Promise<void>;
}

interface MathEnhancerModule {
  enhanceMath(root: HTMLElement, isCurrent: EnhancementGuard): Promise<void>;
}

type CodeModuleLoader = () => Promise<CodeEnhancerModule>;
type MathModuleLoader = () => Promise<MathEnhancerModule>;

const defaultCodeLoader: CodeModuleLoader = () => import("./highlight-code");
const defaultMathLoader: MathModuleLoader = () => import("./render-math");
let codeLoader = defaultCodeLoader;
let mathLoader = defaultMathLoader;
let codeModulePromise: Promise<CodeEnhancerModule> | null = null;
let mathModulePromise: Promise<MathEnhancerModule> | null = null;

function loadCodeModule(): Promise<CodeEnhancerModule> {
  codeModulePromise ??= codeLoader();
  return codeModulePromise;
}

function loadMathModule(): Promise<MathEnhancerModule> {
  mathModulePromise ??= mathLoader();
  return mathModulePromise;
}

export async function enhanceMessage(root: HTMLElement, isCurrent: EnhancementGuard): Promise<void> {
  const jobs: Promise<void>[] = [];
  if (root.querySelector("code[data-code-language]")) {
    jobs.push(loadCodeModule().then((module) => module.enhanceCode(root, isCurrent)));
  }
  if (root.querySelector("[data-math]")) {
    jobs.push(loadMathModule().then((module) => module.enhanceMath(root, isCurrent)));
  }
  await Promise.allSettled(jobs);
}

/** Enhance after `{@html}` lands, and invalidate work when Svelte reuses a node. */
export const enhanceMarkdown: Action<HTMLElement, string> = (node) => {
  let generation = 0;
  const schedule = (): void => {
    const currentGeneration = ++generation;
    queueMicrotask(() => {
      const isCurrent = (): boolean => node.isConnected && generation === currentGeneration;
      if (isCurrent()) void enhanceMessage(node, isCurrent);
    });
  };
  schedule();
  return {
    update() {
      schedule();
    },
    destroy() {
      generation += 1;
    },
  };
};

interface EnhancerLoaderOverrides {
  code?: CodeModuleLoader;
  math?: MathModuleLoader;
}

/** Reset module caches and optionally substitute deterministic loaders in tests. */
export function _setEnhancerLoadersForTest(overrides: EnhancerLoaderOverrides = {}): void {
  codeLoader = overrides.code ?? defaultCodeLoader;
  mathLoader = overrides.math ?? defaultMathLoader;
  codeModulePromise = null;
  mathModulePromise = null;
}
