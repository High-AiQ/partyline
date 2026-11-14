import { mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import A11yLab from "./A11yLab.svelte";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  document.body.replaceChildren();
  vi.clearAllTimers();
  vi.useRealTimers();
});

function element(selector: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(selector);
  if (!found) throw new Error(`missing ${selector}`);
  return found;
}

function button(name: string): HTMLButtonElement {
  const found = element(`[data-event-label="${name}"]`);
  if (!(found instanceof HTMLButtonElement)) throw new Error(`${name} is not a button`);
  return found;
}

function inputElement(selector: string): HTMLInputElement {
  const found = element(selector);
  if (!(found instanceof HTMLInputElement)) throw new Error(`${selector} is not an input`);
  return found;
}

function select(id: string): HTMLSelectElement {
  const found = element(`#${id}`);
  if (!(found instanceof HTMLSelectElement)) throw new Error(`${id} is not a select`);
  return found;
}

function fieldsetElement(): HTMLFieldSetElement {
  const found = element("fieldset");
  if (!(found instanceof HTMLFieldSetElement)) throw new Error("fieldset has the wrong type");
  return found;
}

async function render() {
  const app = mount(A11yLab, { target: document.body });
  await tick();
  return app;
}

async function choose(id: string, value = "A") {
  const control = select(id);
  control.value = value;
  control.dispatchEvent(new Event("change", { bubbles: true }));
  await tick();
}

async function advance(milliseconds: number) {
  await vi.advanceTimersByTimeAsync(milliseconds);
  await tick();
}

describe("accessibility lab", () => {
  it("enables the sync target on change", async () => {
    const app = await render();
    try {
      expect(button("Sync target").disabled).toBe(true);
      await choose("sync-choice");
      expect(button("Sync target").disabled).toBe(false);
    } finally {
      await unmount(app);
    }
  });

  it("enables delayed targets independently at 300 and 2500 milliseconds", async () => {
    const app = await render();
    try {
      await choose("delayed-choice");
      expect(button("Delayed target 300 ms").disabled).toBe(true);
      expect(button("Delayed target 2500 ms").disabled).toBe(true);
      await advance(299);
      expect(button("Delayed target 300 ms").disabled).toBe(true);
      await advance(1);
      expect(button("Delayed target 300 ms").disabled).toBe(false);
      expect(button("Delayed target 2500 ms").disabled).toBe(true);
      await advance(2200);
      expect(button("Delayed target 2500 ms").disabled).toBe(false);
    } finally {
      await unmount(app);
    }
  });

  it("keeps the class-only link aria-disabled after it looks enabled", async () => {
    const app = await render();
    try {
      const link = element('[data-testid="class-only-link"]');
      expect(link.getAttribute("aria-disabled")).toBe("true");
      expect(link.classList.contains("looks-enabled")).toBe(false);
      await choose("class-choice");
      expect(link.classList.contains("looks-enabled")).toBe(true);
      expect(link.getAttribute("aria-disabled")).toBe("true");
    } finally {
      await unmount(app);
    }
  });

  it("removes aria-disabled when the corrected link looks enabled", async () => {
    const app = await render();
    try {
      const link = element('[data-testid="aria-link"]');
      expect(link.getAttribute("aria-disabled")).toBe("true");
      expect(link.classList.contains("looks-enabled")).toBe(false);
      await choose("aria-choice");
      expect(link.classList.contains("looks-enabled")).toBe(true);
      expect(link.hasAttribute("aria-disabled")).toBe(false);
    } finally {
      await unmount(app);
    }
  });

  it("toggles the disabled fieldset ancestor", async () => {
    const app = await render();
    try {
      const checkbox = inputElement('input[type="checkbox"]');
      const fieldset = fieldsetElement();
      expect(checkbox.checked).toBe(true);
      expect(fieldset.disabled).toBe(true);
      checkbox.checked = false;
      checkbox.dispatchEvent(new Event("change", { bubbles: true }));
      await tick();
      expect(fieldset.disabled).toBe(false);
      checkbox.checked = true;
      checkbox.dispatchEvent(new Event("change", { bubbles: true }));
      await tick();
      expect(fieldset.disabled).toBe(true);
    } finally {
      await unmount(app);
    }
  });

  it("increments the count button accessible name", async () => {
    const app = await render();
    try {
      button("Count 0").click();
      await tick();
      expect(button("Count 1")).toBeDefined();
      button("Count 1").click();
      await tick();
      expect(button("Count 2")).toBeDefined();
    } finally {
      await unmount(app);
    }
  });

  it("inserts all three list items after one second", async () => {
    const app = await render();
    try {
      button("Load list").click();
      await tick();
      expect(document.querySelectorAll('[aria-label="Loaded items"] li')).toHaveLength(0);
      await advance(999);
      expect(document.querySelectorAll('[aria-label="Loaded items"] li')).toHaveLength(0);
      await advance(1);
      const items = document.querySelectorAll('[aria-label="Loaded items"] li');
      expect([...items].map((item) => item.textContent)).toEqual(["Item 1", "Item 2", "Item 3"]);
    } finally {
      await unmount(app);
    }
  });

  it("reports input and change events independently on the text field", async () => {
    const app = await render();
    try {
      const input = inputElement("#text-field");
      input.value = "from UIA";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      await tick();
      expect(element('[data-testid="input-event-state"]').textContent).toBe("input fired: yes");
      expect(element('[data-testid="change-event-state"]').textContent).toBe("change fired: no");
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await tick();
      expect(element('[data-testid="change-event-state"]').textContent).toBe("change fired: yes");
    } finally {
      await unmount(app);
    }
  });

  it("logs event names, timestamps and keys and retains only the last twenty", async () => {
    const app = await render();
    try {
      const input = inputElement("#text-field");
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      await tick();
      expect(document.querySelector('[aria-label="Event log"]')?.textContent).toContain(
        "0 ms keydown Text field key=Enter",
      );
      for (let index = 0; index < 25; index += 1) {
        button(`Count ${String(index)}`).click();
        await tick();
      }
      const entries = document.querySelectorAll('[aria-label="Event log"] li');
      expect(entries).toHaveLength(20);
      expect(entries[0]?.textContent).toBe("0 ms click Count 5");
      expect(entries[24 - 5]?.textContent).toBe("0 ms click Count 24");
      expect(document.querySelector('[aria-label="Event log"]')?.getAttribute("aria-live")).toBe("polite");
    } finally {
      await unmount(app);
    }
  });

  it("reset restores every card and cancels pending work", async () => {
    const app = await render();
    try {
      await choose("sync-choice");
      await choose("delayed-choice");
      await choose("class-choice");
      await choose("aria-choice");
      const checkbox = inputElement('input[type="checkbox"]');
      checkbox.checked = false;
      checkbox.dispatchEvent(new Event("change", { bubbles: true }));
      button("Count 0").click();
      button("Load list").click();
      const input = inputElement("#text-field");
      input.value = "pending";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await advance(300);
      button("Reset lab").click();
      await tick();

      expect(select("sync-choice").value).toBe("");
      expect(select("delayed-choice").value).toBe("");
      expect(select("class-choice").value).toBe("");
      expect(select("aria-choice").value).toBe("");
      expect(button("Sync target").disabled).toBe(true);
      expect(button("Delayed target 300 ms").disabled).toBe(true);
      expect(button("Delayed target 2500 ms").disabled).toBe(true);
      expect(element('[data-testid="class-only-link"]').classList.contains("looks-enabled")).toBe(false);
      expect(element('[data-testid="class-only-link"]').getAttribute("aria-disabled")).toBe("true");
      expect(element('[data-testid="aria-link"]').getAttribute("aria-disabled")).toBe("true");
      expect(checkbox.checked).toBe(true);
      expect(fieldsetElement().disabled).toBe(true);
      expect(button("Count 0")).toBeDefined();
      expect(document.querySelector('[aria-label="Loaded items"]')).toBeNull();
      expect(input.value).toBe("");
      expect(element('[data-testid="input-event-state"]').textContent).toBe("input fired: no");
      expect(element('[data-testid="change-event-state"]').textContent).toBe("change fired: no");
      expect(document.querySelector('[aria-label="Event log"]')?.textContent).toBe("No events yet.");
      await advance(5000);
      expect(button("Delayed target 300 ms").disabled).toBe(true);
      expect(button("Delayed target 2500 ms").disabled).toBe(true);
      expect(document.querySelector('[aria-label="Loaded items"]')).toBeNull();
    } finally {
      await unmount(app);
    }
  });
});
