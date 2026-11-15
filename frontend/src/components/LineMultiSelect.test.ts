import { mount, tick, unmount } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import LineMultiSelect from "./LineMultiSelect.svelte";

const options = [
  { id: "a", name: "Alpha" },
  { id: "b", name: "Beta" },
];
afterEach(() => {
  document.body.replaceChildren();
});
function input(): HTMLInputElement {
  const element = document.querySelector("input");
  if (!element) throw new Error("missing combobox");
  return element;
}
async function key(value: string): Promise<void> {
  input().dispatchEvent(new KeyboardEvent("keydown", { key: value, bubbles: true, cancelable: true }));
  await tick();
}
it("exposes a labeled multiselect listbox, filters and toggles with arrows, Enter and Space", async () => {
  const change = vi.fn();
  const component = mount(LineMultiSelect, {
    target: document.body,
    props: { label: "Window lines", options, selected: ["a"], onchange: change },
  });
  await tick();
  expect(document.querySelector("label")?.htmlFor).toBe(input().id);
  expect(input().getAttribute("role")).toBe("combobox");
  expect(input().getAttribute("aria-expanded")).toBe("false");
  await key("ArrowDown");
  expect(input().getAttribute("aria-expanded")).toBe("true");
  expect(document.querySelector('[role="listbox"]')?.getAttribute("aria-multiselectable")).toBe("true");
  expect(document.querySelector('[role="option"]')?.getAttribute("aria-selected")).toBe("true");
  await key("ArrowDown");
  expect(document.getElementById(input().getAttribute("aria-activedescendant") ?? "")?.textContent).toContain(
    "Beta",
  );
  await key("Enter");
  expect(change).toHaveBeenLastCalledWith(["a", "b"]);
  await key("ArrowUp");
  await key(" ");
  expect(change).toHaveBeenLastCalledWith([]);
  input().value = "bet";
  input().dispatchEvent(new Event("input", { bubbles: true }));
  await tick();
  expect(document.querySelectorAll('[role="option"]')).toHaveLength(1);
  await key("Enter");
  expect(change).toHaveBeenLastCalledWith(["a", "b"]);
  input().value = "no match";
  input().dispatchEvent(new Event("input", { bubbles: true }));
  await tick();
  expect(document.body.textContent).toContain("No matching lines");
  await key("ArrowDown");
  await key("Enter");
  const outerEscape = vi.fn();
  window.addEventListener("keydown", outerEscape);
  await key("Escape");
  expect(outerEscape).not.toHaveBeenCalled();
  window.removeEventListener("keydown", outerEscape);
  expect(input().getAttribute("aria-expanded")).toBe("false");
  await unmount(component);
});
it("removes chips with Backspace or their named button and closes on focus leaving", async () => {
  const change = vi.fn();
  const component = mount(LineMultiSelect, {
    target: document.body,
    props: { label: "Lines", options, selected: ["a", "b"], onchange: change },
  });
  await tick();
  await key("Backspace");
  expect(change).toHaveBeenLastCalledWith(["a"]);
  document.querySelector<HTMLButtonElement>('[aria-label="Remove Alpha"]')?.click();
  expect(change).toHaveBeenLastCalledWith(["b"]);
  input().focus();
  await tick();
  input().blur();
  await tick();
  expect(input().getAttribute("aria-expanded")).toBe("false");
  await unmount(component);
});

it("keeps spaces in a multiword filter from granting or revoking access", async () => {
  const change = vi.fn();
  const component = mount(LineMultiSelect, {
    target: document.body,
    props: {
      label: "Lines",
      options: [
        { id: "dev", name: "partyline dev" },
        { id: "review", name: "partyline review" },
      ],
      selected: ["dev"],
      onchange: change,
    },
  });
  await tick();
  input().focus();
  input().value = "partyline";
  input().dispatchEvent(new Event("input", { bubbles: true }));
  await tick();
  const space = new KeyboardEvent("keydown", { key: " ", bubbles: true, cancelable: true });
  input().dispatchEvent(space);
  expect(space.defaultPrevented).toBe(false);
  expect(change).not.toHaveBeenCalled();
  input().value = "partyline dev";
  input().dispatchEvent(new Event("input", { bubbles: true }));
  await tick();
  expect(document.querySelectorAll('[role="option"]')).toHaveLength(1);
  expect(document.querySelector('[role="option"]')?.textContent).toContain("partyline dev");
  expect(change).not.toHaveBeenCalled();
  await key("Enter");
  expect(change).toHaveBeenCalledExactlyOnceWith([]);
  await unmount(component);
});
