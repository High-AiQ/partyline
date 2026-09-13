import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import ProcessTraits from "./ProcessTraits.svelte";
import { defaultPresetTraits, type PresetTraitValues } from "../lib/preset-traits";

afterEach(() => {
  document.body.replaceChildren();
});

describe("ProcessTraits", () => {
  it("defaults implements on and the other two off", () => {
    let traits = defaultPresetTraits();
    const component = mount(ProcessTraits, {
      target: document.body,
      props: {
        get traits() {
          return traits;
        },
        set traits(value: PresetTraitValues) {
          traits = value;
        },
      },
    });
    try {
      const reads = document.querySelector("#trait-reads_images");
      const manage = document.querySelector("#trait-can_manage");
      const implementsBox = document.querySelector("#trait-implements");
      if (
        !(reads instanceof HTMLInputElement) ||
        !(manage instanceof HTMLInputElement) ||
        !(implementsBox instanceof HTMLInputElement)
      ) {
        throw new Error("missing trait checkboxes");
      }
      expect(reads.checked).toBe(false);
      expect(manage.checked).toBe(false);
      expect(implementsBox.checked).toBe(true);
    } finally {
      void unmount(component);
    }
  });

  it("assigns a new traits object when a checkbox is toggled", async () => {
    let traits = defaultPresetTraits();
    const seeded = traits;
    const component = mount(ProcessTraits, {
      target: document.body,
      props: {
        get traits() {
          return traits;
        },
        set traits(value: PresetTraitValues) {
          traits = value;
        },
      },
    });
    try {
      const reads = document.querySelector("#trait-reads_images");
      if (!(reads instanceof HTMLInputElement)) throw new Error("missing reads_images checkbox");
      reads.click();
      await tick();
      expect(traits).not.toBe(seeded);
      expect(traits.reads_images).toBe(true);
      expect(traits.can_manage).toBe(false);
      expect(traits.implements).toBe(true);
    } finally {
      void unmount(component);
    }
  });
});
