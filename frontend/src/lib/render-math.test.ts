import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  enhanceMath,
  loadKatex,
  _setKatexLoaderForTest,
  MAX_EXPRESSION_BYTES,
  MAX_EXPRESSIONS_PER_MESSAGE,
} from "./render-math";

describe("render-math", () => {
  beforeEach(() => {
    _setKatexLoaderForTest(null);
  });

  it("loads KaTeX dynamically and memoizes the promise", async () => {
    const k1 = await loadKatex();
    const k2 = await loadKatex();
    expect(k1).toBeDefined();
    expect(typeof k1.render).toBe("function");
    expect(k1).toBe(k2);
  });

  it("does nothing when container has no math elements", async () => {
    const container = document.createElement("div");
    container.innerHTML = "<p>Plain text without math</p>";
    await enhanceMath(container);
    expect(container.innerHTML).toBe("<p>Plain text without math</p>");
  });

  it("renders inline math with displayMode=false and sets rendered marker", async () => {
    const container = document.createElement("div");
    container.innerHTML = '<p>Energy: <span data-math="inline">E = mc^2</span></p>';
    await enhanceMath(container);

    const span = container.querySelector<HTMLElement>("[data-math]");
    expect(span).not.toBeNull();
    expect(span?.dataset.mathRendered).toBe("true");
    expect(span?.querySelector(".katex")).not.toBeNull();
    expect(span?.querySelector(".katex-mathml")).not.toBeNull();
    expect(span?.querySelector(".katex-html")).not.toBeNull();
  });

  it("renders display math with displayMode=true", async () => {
    const container = document.createElement("div");
    container.innerHTML = '<div data-math="display">\\int_0^1 x^2\\,dx</div>';
    await enhanceMath(container);

    const el = container.querySelector<HTMLElement>("[data-math]");
    expect(el?.dataset.mathRendered).toBe("true");
    const katexDisplay = el?.querySelector(".katex-display");
    expect(katexDisplay).not.toBeNull();
  });

  it("uses the locked-down options and isolates macros between expressions", async () => {
    const katex = await loadKatex();
    const render = vi.spyOn(katex, "render");
    const container = document.createElement("div");
    container.innerHTML = '<span data-math="inline">x</span><span data-math="display">y</span>';
    await enhanceMath(container);

    const first = render.mock.calls[0]?.[2];
    const second = render.mock.calls[1]?.[2];
    expect(first).toMatchObject({
      displayMode: false,
      throwOnError: false,
      strict: "warn",
      trust: false,
      output: "htmlAndMathml",
    });
    expect(second).toMatchObject({ displayMode: true, trust: false });
    expect(first?.macros).not.toBe(second?.macros);
    render.mockRestore();
  });

  it("is idempotent when called multiple times on the same tree", async () => {
    const container = document.createElement("div");
    container.innerHTML = '<span data-math="inline">x + y = z</span>';
    await enhanceMath(container);
    const htmlFirst = container.innerHTML;

    await enhanceMath(container);
    expect(container.innerHTML).toBe(htmlFirst);
  });

  it("handles malformed TeX gracefully without throwing", async () => {
    const container = document.createElement("div");
    container.innerHTML = '<span data-math="inline">\\invalidMacro{foo}</span>';
    await expect(enhanceMath(container)).resolves.not.toThrow();

    const span = container.querySelector<HTMLElement>("[data-math]");
    expect(span?.dataset.mathRendered).toBe("true");
    expect(span?.innerHTML).toContain("katex");
  });

  it("leaves expressions exceeding MAX_EXPRESSION_BYTES as literal source", async () => {
    const hugeTex = "\\text{" + "a".repeat(MAX_EXPRESSION_BYTES + 10) + "}";
    const container = document.createElement("div");
    const span = document.createElement("span");
    span.setAttribute("data-math", "inline");
    span.textContent = hugeTex;
    container.appendChild(span);

    await enhanceMath(container);
    expect(span.dataset.mathRendered).toBeUndefined();
    expect(span.textContent).toBe(hugeTex);
  });

  it("caps processing at MAX_EXPRESSIONS_PER_MESSAGE", async () => {
    const container = document.createElement("div");
    for (let i = 0; i < MAX_EXPRESSIONS_PER_MESSAGE + 5; i++) {
      const span = document.createElement("span");
      span.setAttribute("data-math", "inline");
      span.textContent = `x_{${String(i)}}`;
      container.appendChild(span);
    }

    await enhanceMath(container);
    const spans = container.querySelectorAll<HTMLElement>("[data-math]");
    expect(spans).toHaveLength(MAX_EXPRESSIONS_PER_MESSAGE + 5);

    let renderedCount = 0;
    spans.forEach((s) => {
      if (s.dataset.mathRendered === "true") renderedCount++;
    });
    expect(renderedCount).toBe(MAX_EXPRESSIONS_PER_MESSAGE);
  });

  it("ignores unknown data-math values", async () => {
    const container = document.createElement("div");
    container.innerHTML = '<span data-math="unsupported">x = 1</span>';
    await enhanceMath(container);
    const span = container.querySelector<HTMLElement>("[data-math]");
    expect(span?.dataset.mathRendered).toBeUndefined();
    expect(span?.textContent).toBe("x = 1");
  });

  it("handles loader failure without throwing or blanking content", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const container = document.createElement("div");
    container.innerHTML = '<span data-math="inline">a + b</span>';

    // Mock load failure using test hook
    _setKatexLoaderForTest(() => Promise.reject(new Error("Network offline")));

    await expect(enhanceMath(container)).resolves.not.toThrow();
    const span = container.querySelector<HTMLElement>("[data-math]");
    expect(span?.dataset.mathRendered).toBeUndefined();
    expect(span?.textContent).toBe("a + b");

    warnSpy.mockRestore();
  });

  it("memoizes rejection so repeated enhancement attempts invoke a failing loader only once", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const loaderSpy = vi.fn(() => Promise.reject(new Error("Chunk 404")));
    _setKatexLoaderForTest(loaderSpy);

    const c1 = document.createElement("div");
    c1.innerHTML = '<span data-math="inline">x</span>';
    const c2 = document.createElement("div");
    c2.innerHTML = '<span data-math="inline">y</span>';

    await enhanceMath(c1);
    await enhanceMath(c2);

    expect(loaderSpy).toHaveBeenCalledTimes(1);
    expect(c1.querySelector("span")?.dataset.mathRendered).toBeUndefined();
    expect(c2.querySelector("span")?.dataset.mathRendered).toBeUndefined();

    warnSpy.mockRestore();
  });

  it("does not mutate a stale message after its lazy import resolves", async () => {
    let resolveLoader: (katex: typeof import("katex")) => void = () => undefined;
    const loader = new Promise<typeof import("katex")>((resolve) => {
      resolveLoader = resolve;
    });
    _setKatexLoaderForTest(() => loader);
    const container = document.createElement("div");
    container.innerHTML = '<span data-math="inline">x</span>';
    let current = true;

    const enhancement = enhanceMath(container, () => current);
    current = false;
    resolveLoader(await import("katex"));
    await enhancement;

    expect(container.querySelector("span")?.dataset.mathRendered).toBeUndefined();
    expect(container.textContent).toBe("x");
  });
});
