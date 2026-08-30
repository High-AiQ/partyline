import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LanguageFn } from "highlight.js";
import { _setHighlightLoadersForTest, enhanceCode } from "./highlight-code";
import { CODE_BLOCK_MAX_BYTES } from "./markdown-contract";

const grammar: LanguageFn = () => ({ name: "test", contains: [] });

function markedCode(language = "python", source = "print('hi')"): HTMLElement {
  const root = document.createElement("div");
  const code = document.createElement("code");
  code.dataset.codeLanguage = language;
  code.textContent = source;
  root.append(code);
  return root;
}

function fakeEngine() {
  return {
    registerLanguage: vi.fn(),
    highlight: vi.fn((source: string) => ({ value: `<span class="hljs-keyword">${source}</span>` })),
  };
}

describe("highlight-code", () => {
  beforeEach(() => {
    _setHighlightLoadersForTest();
  });

  it("does not load anything for a message without a marked fence", async () => {
    const core = vi.fn(() => Promise.resolve(fakeEngine()));
    _setHighlightLoadersForTest({ core });
    await enhanceCode(document.createElement("div"));
    expect(core).not.toHaveBeenCalled();
  });

  it("highlights with a registered allowlisted grammar and is idempotent", async () => {
    const engine = fakeEngine();
    const core = vi.fn(() => Promise.resolve(engine));
    const language = vi.fn(() => Promise.resolve(grammar));
    _setHighlightLoadersForTest({ core, languages: { python: language } });
    const root = markedCode();

    await enhanceCode(root);
    await enhanceCode(root);

    const code = root.querySelector("code");
    expect(code?.dataset.codeHighlighted).toBe("true");
    expect(code?.querySelector(".hljs-keyword")?.textContent).toBe("print('hi')");
    expect(core).toHaveBeenCalledTimes(1);
    expect(language).toHaveBeenCalledTimes(1);
    expect(engine.registerLanguage).toHaveBeenCalledTimes(1);
    expect(engine.highlight).toHaveBeenCalledTimes(1);
  });

  it("uses highlight.js output that keeps hostile source as text", async () => {
    const source = '<img src=x onerror="alert(1)">\nconst value = 1;';
    const root = markedCode("javascript", source);
    await enhanceCode(root);
    const code = root.querySelector("code");
    expect(code?.querySelector("img")).toBeNull();
    expect(code?.textContent).toBe(source);
    expect(code?.querySelector(".hljs-keyword")?.textContent).toBe("const");
  });

  it("leaves unsupported and oversized blocks plain without importing core", async () => {
    const core = vi.fn(() => Promise.resolve(fakeEngine()));
    _setHighlightLoadersForTest({ core });
    const unknown = markedCode("ruby");
    const oversized = markedCode("python", "x".repeat(CODE_BLOCK_MAX_BYTES + 1));
    await Promise.all([enhanceCode(unknown), enhanceCode(oversized)]);
    expect(core).not.toHaveBeenCalled();
    expect(unknown.querySelector("code")?.dataset.codeHighlighted).toBeUndefined();
    expect(oversized.querySelector("code")?.dataset.codeHighlighted).toBeUndefined();
  });

  it("memoizes failed imports without blanking or hot-retrying", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const core = vi.fn(() => Promise.reject(new Error("chunk missing")));
    _setHighlightLoadersForTest({ core, languages: { python: () => Promise.resolve(grammar) } });
    const first = markedCode();
    const second = markedCode();
    await enhanceCode(first);
    await enhanceCode(second);
    expect(core).toHaveBeenCalledTimes(1);
    expect(first.textContent).toBe("print('hi')");
    expect(second.textContent).toBe("print('hi')");
    warn.mockRestore();
  });

  it("does not mutate a stale node after a delayed import", async () => {
    const engine = fakeEngine();
    let resolveCore: (value: ReturnType<typeof fakeEngine>) => void = () => undefined;
    const pending = new Promise<ReturnType<typeof fakeEngine>>((resolve) => {
      resolveCore = resolve;
    });
    _setHighlightLoadersForTest({
      core: () => pending,
      languages: { python: () => Promise.resolve(grammar) },
    });
    const root = markedCode();
    let current = true;
    const enhancement = enhanceCode(root, () => current);
    current = false;
    resolveCore(engine);
    await enhancement;
    expect(root.querySelector("code")?.dataset.codeHighlighted).toBeUndefined();
    expect(engine.highlight).not.toHaveBeenCalled();
  });
});
