import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fixtureNames, type FixtureName } from "./fixtures";
import { mountFixture } from "./main";

function required<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error("expected fixture element to exist");
  return value;
}

function eventTarget(name: FixtureName, root: HTMLElement): HTMLElement {
  if (name === "shadow-open") {
    const shadow = required(required(root.querySelector("open-target")).shadowRoot);
    return required(shadow.querySelector<HTMLElement>("button"));
  }
  if (name === "shadow-nested") {
    const outer = required(required(root.querySelector("nested-target")).shadowRoot);
    const inner = required(required(outer.querySelector("inner-target")).shadowRoot);
    const child = required(required(inner.querySelector("div")).shadowRoot);
    return required(child.querySelector<HTMLElement>("button"));
  }
  const selectors: Record<FixtureName, string> = {
    "shadow-open": "",
    "shadow-nested": "",
    "shadow-slotted": "#slotted-target",
    "shadow-closed": "closed-target",
    overlay: "#target",
    "iframe-same-origin": "iframe",
    "iframe-cross-origin": "iframe",
    "select-native": "#target",
    "listbox-custom": "#listbox",
    "combobox-filter": "#combo",
    "input-text": "#target",
    textarea: "#target",
    contenteditable: "#target",
    password: "#target",
    "file-input": "#target",
    "file-chooser": "#chooser",
    "scroll-container": "#target",
    "delayed-animated": "#target",
    modal: "#target",
    toast: "#toast",
    navigation: "#target",
    canvas: "#canvas",
    frame: "#frame-target",
  };
  return required(root.querySelector<HTMLElement>(selectors[name]));
}

function expectedTarget(name: FixtureName): string {
  if (name === "shadow-closed") return "CLOSED-TARGET";
  if (name === "iframe-same-origin") return "IFRAME";
  if (name === "iframe-cross-origin") return "cross-frame";
  const target = {
    "shadow-open": "target",
    "shadow-nested": "target",
    "shadow-slotted": "slotted-target",
  } as Partial<Record<FixtureName, string>>;
  return (
    target[name] ??
    (name === "listbox-custom"
      ? "listbox"
      : name === "combobox-filter"
        ? "combo"
        : name === "canvas"
          ? "canvas"
          : name === "file-chooser"
            ? "chooser"
            : name === "toast"
              ? "toast"
              : name === "frame"
                ? "frame-target"
                : "target")
  );
}

describe("window bench page event wiring", () => {
  beforeEach(() => {
    document.body.replaceChildren();
    document.head.replaceChildren();
  });

  afterEach(() => vi.restoreAllMocks());

  it.each(fixtureNames)("records event trust, type and target on the %s page", (name) => {
    const root = document.createElement("main");
    root.id = "root";
    document.body.append(root);
    if (name === "canvas") {
      const context = { fillStyle: "", font: "", fillRect: vi.fn(), fillText: vi.fn() };
      vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as never);
    }
    let trustedOverride = false;
    // jsdom events are always untrusted; this injectable source exercises the real trusted rendering branch.
    const cleanup = mountFixture(
      root,
      `/lab/window-bench/${name}.html`,
      "",
      (event) => trustedOverride || event.isTrusted,
    );
    const target = eventTarget(name, root);
    const log = required(root.querySelector<HTMLOListElement>("#event-log"));

    const untrusted = new Event("click", { bubbles: true, composed: true });
    target.dispatchEvent(untrusted);
    expect(untrusted.isTrusted).toBe(false);

    trustedOverride = true;
    const trustedBranch = new Event("click", { bubbles: true, composed: true });
    target.dispatchEvent(trustedBranch);

    const entries = [...log.querySelectorAll("li")].filter(
      (entry) => entry.dataset.target === expectedTarget(name),
    );
    expect(entries.map((entry) => entry.dataset.isTrusted)).toEqual(["false", "true"]);
    expect(entries.map((entry) => entry.dataset.eventType)).toEqual(["click", "click"]);
    expect(entries[1]?.textContent).toBe(`isTrusted=true type=click target=${expectedTarget(name)}`);
    cleanup();
  });
});
