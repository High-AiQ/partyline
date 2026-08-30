import { beforeEach, describe, expect, it, vi } from "vitest";
import { _setEnhancerLoadersForTest, enhanceMarkdown, enhanceMessage } from "./message-enhancers";

function rootWith(markup: string): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = markup;
  return root;
}

describe("message-enhancers", () => {
  beforeEach(() => {
    _setEnhancerLoadersForTest();
  });

  it("imports no enhancer for ordinary text", async () => {
    const code = vi.fn();
    const math = vi.fn();
    _setEnhancerLoadersForTest({ code, math });
    await enhanceMessage(rootWith("<p>plain</p>"), () => true);
    expect(code).not.toHaveBeenCalled();
    expect(math).not.toHaveBeenCalled();
  });

  it("loads only the enhancer whose inert marker is present", async () => {
    const enhanceCode = vi.fn(() => Promise.resolve());
    const enhanceMath = vi.fn(() => Promise.resolve());
    const code = vi.fn(() => Promise.resolve({ enhanceCode }));
    const math = vi.fn(() => Promise.resolve({ enhanceMath }));
    _setEnhancerLoadersForTest({ code, math });

    await enhanceMessage(rootWith('<pre><code data-code-language="python">x</code></pre>'), () => true);
    expect(code).toHaveBeenCalledTimes(1);
    expect(enhanceCode).toHaveBeenCalledTimes(1);
    expect(math).not.toHaveBeenCalled();

    await enhanceMessage(rootWith('<span data-math="inline">x</span>'), () => true);
    expect(math).toHaveBeenCalledTimes(1);
    expect(enhanceMath).toHaveBeenCalledTimes(1);
    expect(code).toHaveBeenCalledTimes(1);
  });

  it("memoizes enhancer modules across messages", async () => {
    const enhanceCode = vi.fn(() => Promise.resolve());
    const code = vi.fn(() => Promise.resolve({ enhanceCode }));
    _setEnhancerLoadersForTest({ code });
    const markup = '<code data-code-language="python">x</code>';
    await enhanceMessage(rootWith(markup), () => true);
    await enhanceMessage(rootWith(markup), () => true);
    expect(code).toHaveBeenCalledTimes(1);
    expect(enhanceCode).toHaveBeenCalledTimes(2);
  });

  it("contains and memoizes a rejected module import", async () => {
    const code = vi.fn(() => Promise.reject(new Error("offline")));
    _setEnhancerLoadersForTest({ code });
    const markup = '<code data-code-language="python">x</code>';
    await expect(enhanceMessage(rootWith(markup), () => true)).resolves.not.toThrow();
    await expect(enhanceMessage(rootWith(markup), () => true)).resolves.not.toThrow();
    expect(code).toHaveBeenCalledTimes(1);
  });

  it("cancels a queued action when its node is destroyed", async () => {
    const code = vi.fn();
    _setEnhancerLoadersForTest({ code });
    const root = rootWith('<code data-code-language="python">x</code>');
    document.body.append(root);
    const action = enhanceMarkdown(root, "first");
    action?.destroy?.();
    await Promise.resolve();
    expect(code).not.toHaveBeenCalled();
    root.remove();
  });
});
