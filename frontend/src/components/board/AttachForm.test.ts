import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import AttachForm from "./AttachForm.svelte";
import type { Adapter, Preset } from "../../lib/contracts";
import { session } from "../../state/session.svelte.js";

const adapter: Adapter = {
  id: "codex",
  command: ["codex"],
  capabilities: {},
  overrides_bundled: false,
  update_command: null,
  compact_paste: null,
};

const preset: Preset = {
  id: "preset-1",
  title: "captain",
  name: "sol",
  adapter: "codex",
  command: "codex",
  created_at: 1,
  reads_images: true,
  can_manage: true,
  implements: false,
};

afterEach(() => {
  session.adapters = [];
  session.presets = [];
  document.body.replaceChildren();
});

describe("AttachForm process traits", () => {
  it("does not render stray text between save and manage", () => {
    session.adapters = [adapter];
    const form = mount(AttachForm, { target: document.body });
    try {
      const row = document.querySelector("#presetRow");
      if (!(row instanceof HTMLElement)) throw new Error("missing #presetRow");
      const stray = [...row.childNodes]
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => (node.textContent ?? "").trim())
        .filter(Boolean);
      expect(stray).toEqual([]);
      expect(row.textContent.replace(/\s+/g, " ").trim()).toBe("— none — save manage");
    } finally {
      void unmount(form);
    }
  });

  it("hides the trait checkboxes behind a process traits accordion", () => {
    session.adapters = [adapter];
    const form = mount(AttachForm, { target: document.body });
    try {
      const details = document.querySelector("#processTraits");
      if (!(details instanceof HTMLDetailsElement)) throw new Error("missing #processTraits");
      const summary = details.querySelector("summary");
      expect(summary?.textContent).toBe("process traits");
      expect(details.open).toBe(false);
    } finally {
      void unmount(form);
    }
  });

  it("shows the three trait labels once the accordion is opened", async () => {
    session.adapters = [adapter];
    const form = mount(AttachForm, { target: document.body });
    try {
      const details = document.querySelector("#processTraits");
      if (!(details instanceof HTMLDetailsElement)) throw new Error("missing #processTraits");
      details.open = true;
      await tick();
      expect(details.textContent).toContain("Reads images");
      expect(details.textContent).toContain("Can manage a line");
      expect(details.textContent).toContain("Fast implementer");
    } finally {
      void unmount(form);
    }
  });

  it("copies a preset's trait flags onto the attach checkboxes", async () => {
    session.adapters = [adapter];
    session.presets = [preset];
    const form = mount(AttachForm, { target: document.body });
    try {
      const select = document.querySelector("#aPreset");
      if (!(select instanceof HTMLSelectElement)) throw new Error("missing preset select");
      select.value = preset.id;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      await tick();

      const details = document.querySelector("#processTraits");
      if (!(details instanceof HTMLDetailsElement)) throw new Error("missing #processTraits");
      details.open = true;
      await tick();

      const reads = document.querySelector("#attach-trait-reads_images");
      const manage = document.querySelector("#attach-trait-can_manage");
      const implementsBox = document.querySelector("#attach-trait-implements");
      if (
        !(reads instanceof HTMLInputElement) ||
        !(manage instanceof HTMLInputElement) ||
        !(implementsBox instanceof HTMLInputElement)
      ) {
        throw new Error("missing attach trait checkboxes");
      }
      expect(reads.checked).toBe(true);
      expect(manage.checked).toBe(true);
      expect(implementsBox.checked).toBe(false);
    } finally {
      void unmount(form);
    }
  });
});
