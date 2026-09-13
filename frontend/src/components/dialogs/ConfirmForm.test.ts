import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ConfirmForm from "./ConfirmForm.svelte";

afterEach(() => {
  document.body.replaceChildren();
});

describe("destructive line confirmation", () => {
  it("keeps the destructive submit disabled until the exact line name is entered", async () => {
    const onconfirm = vi.fn();
    const component = mount(ConfirmForm, {
      target: document.body,
      props: {
        phrase: "Frontend Polish",
        label: "close processes",
        prompt: "type the line name to confirm",
        onconfirm,
        oncancel: vi.fn(),
      },
    });
    try {
      const input = document.querySelector("#confirmPhrase");
      const submit = document.querySelector("button.danger");
      if (!(input instanceof HTMLInputElement) || !(submit instanceof HTMLButtonElement)) {
        throw new Error("missing confirmation controls");
      }
      expect(submit.disabled).toBe(true);
      input.value = "frontend polish";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      await tick();
      expect(submit.disabled).toBe(true);
      input.value = "Frontend Polish";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      await tick();
      expect(submit.disabled).toBe(false);
    } finally {
      await unmount(component);
    }
  });
});
