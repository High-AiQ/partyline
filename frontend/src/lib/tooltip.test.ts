import { afterEach, describe, expect, it } from "vitest";
import { clampTooltipLeft, tooltip } from "./tooltip";

afterEach(() => {
  document.body.replaceChildren();
});

describe("tooltip action", () => {
  it("describes a control and reveals the app tooltip on hover and focus", () => {
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
    expect(clampTooltipLeft(4, 80, 320)).toBe(48);
    expect(clampTooltipLeft(316, 80, 320)).toBe(272);
    expect(clampTooltipLeft(160, 400, 320)).toBe(160);
  });

  it("places a tooltip below a control too close to the top edge", () => {
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
