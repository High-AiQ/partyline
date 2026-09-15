import { afterEach, describe, expect, it, vi } from "vitest";
import { clampTooltipLeft, tooltip, tooltipsEnabled } from "./tooltip";

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("tooltip action", () => {
  it("describes a control and reveals the app tooltip on hover and focus", () => {
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    const button = document.createElement("button");
    document.body.append(button);
    const action = tooltip(button, { label: "open lines" });
    const tooltipId = button.getAttribute("aria-describedby");
    expect(tooltipId).toBeTruthy();
    const tipElement = tooltipId ? document.getElementById(tooltipId) : null;
    if (!(tipElement instanceof HTMLSpanElement)) throw new Error("missing tooltip");
    const tip = tipElement;
    expect(tip.getAttribute("role")).toBe("tooltip");
    expect(tip.hidden).toBe(true);

    button.dispatchEvent(new MouseEvent("mouseenter"));
    expect(tip.hidden).toBe(false);
    expect(tip.textContent).toBe("open lines");
    button.dispatchEvent(new MouseEvent("mouseleave"));
    expect(tip.hidden).toBe(true);

    button.dispatchEvent(new FocusEvent("focus"));
    expect(tip.hidden).toBe(false);
    button.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(tip.hidden).toBe(true);
    action.destroy();
    expect(document.querySelector('[role="tooltip"]')).toBeNull();
  });

  it("keeps the actual tooltip box inside the viewport", () => {
    expect(clampTooltipLeft(-36, 80, 320)).toBe(8);
    expect(clampTooltipLeft(276, 80, 320)).toBe(232);
    expect(clampTooltipLeft(8, 304, 320)).toBe(8);
  });

  it("places a tooltip below a control too close to the top edge", () => {
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    const button = document.createElement("button");
    document.body.append(button);
    Object.defineProperty(button, "getBoundingClientRect", {
      value: () => new DOMRect(120, 10, 40, 20),
    });
    const action = tooltip(button, { label: "top edge" });
    const tooltipId = button.getAttribute("aria-describedby");
    if (!tooltipId) throw new Error("missing tooltip description");
    const tip = document.getElementById(tooltipId);
    if (!(tip instanceof HTMLSpanElement)) throw new Error("missing tooltip");
    button.dispatchEvent(new MouseEvent("mouseenter"));
    expect(tip.classList.contains("app-tooltip-below")).toBe(true);
    expect(tip.style.top).toBe("38px");
    action.destroy();
  });

  it("follows the pointer below the cursor when asked", () => {
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    const button = document.createElement("button");
    document.body.append(button);
    Object.defineProperty(button, "getBoundingClientRect", {
      value: () => new DOMRect(120, 10, 40, 20),
    });
    const action = tooltip(button, { label: "topic hint", placement: "below", followCursor: true });
    const tooltipId = button.getAttribute("aria-describedby");
    if (!tooltipId) throw new Error("missing tooltip description");
    const tip = document.getElementById(tooltipId);
    if (!(tip instanceof HTMLSpanElement)) throw new Error("missing tooltip");
    button.dispatchEvent(new MouseEvent("mouseenter", { clientX: 180, clientY: 64 }));
    button.dispatchEvent(new MouseEvent("mousemove", { clientX: 180, clientY: 64 }));
    expect(tip.classList.contains("app-tooltip-below")).toBe(true);
    expect(tip.style.top).toBe("76px");
    action.destroy();
  });

  it("does not show tooltips on narrow or touch-only viewports", () => {
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: query.includes("899px") || query.includes("hover: none"),
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    expect(tooltipsEnabled()).toBe(false);
    const button = document.createElement("button");
    document.body.append(button);
    const action = tooltip(button, { label: "hidden on mobile" });
    const tooltipId = button.getAttribute("aria-describedby");
    if (!tooltipId) throw new Error("missing tooltip description");
    const tip = document.getElementById(tooltipId);
    if (!(tip instanceof HTMLSpanElement)) throw new Error("missing tooltip");
    button.dispatchEvent(new MouseEvent("mouseenter"));
    expect(tip.hidden).toBe(true);
    action.destroy();
  });

  it("removes its description when the label becomes empty", () => {
    const span = document.createElement("span");
    document.body.append(span);
    const action = tooltip(span, { label: "details" });
    const tipId = span.getAttribute("aria-describedby");
    action.update({ label: "" });
    expect(span.hasAttribute("aria-describedby")).toBe(false);
    expect(tipId ? document.getElementById(tipId) : null).toBeNull();
    action.destroy();
  });
});
