import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import PresetCard from "./PresetCard.svelte";
import { api } from "../../lib/api";
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
  vi.restoreAllMocks();
  session.adapters = [];
  session.presets = [];
  document.body.replaceChildren();
});

describe("PresetCard process traits", () => {
  it("shows the four trait checkboxes on a manage card", () => {
    session.adapters = [adapter];
    const card = mount(PresetCard, { target: document.body, props: { preset } });
    try {
      expect(document.querySelector("#pTrait-preset-1-reads_images")).toBeInstanceOf(HTMLInputElement);
      expect(document.querySelector("#pTrait-preset-1-can_manage")).toBeInstanceOf(HTMLInputElement);
      expect(document.querySelector("#pTrait-preset-1-implements")).toBeInstanceOf(HTMLInputElement);
      expect(document.body.textContent).toContain("Reads images");
      expect(document.body.textContent).toContain("Can manage a line");
      expect(document.body.textContent).toContain("Fast implementer");
      expect(document.body.textContent).toContain("Emitter");
    } finally {
      void unmount(card);
    }
  });

  it("includes all four trait flags on the save payload", async () => {
    session.adapters = [adapter];
    const savePreset = vi.spyOn(api, "savePreset").mockResolvedValue(preset);
    vi.spyOn(session, "loadPresets").mockResolvedValue();
    const card = mount(PresetCard, { target: document.body, props: { preset } });
    try {
      document.querySelector<HTMLButtonElement>("button.save")?.click();
      await vi.waitFor(() => {
        expect(savePreset).toHaveBeenCalledWith({
          id: "preset-1",
          title: "captain",
          name: "sol",
          adapter: "codex",
          command: "codex",
          reads_images: true,
          can_manage: true,
          implements: false,
          emitter: false,
          max_compactions: null,
        });
      });
    } finally {
      void unmount(card);
    }
  });

  it("locks and saves effective emitter traits on a legacy raw preset", async () => {
    const raw = { ...preset, adapter: "raw", implements: true };
    session.adapters = [{ ...adapter, id: "raw" }];
    const savePreset = vi.spyOn(api, "savePreset").mockResolvedValue(raw);
    vi.spyOn(session, "loadPresets").mockResolvedValue();
    const card = mount(PresetCard, { target: document.body, props: { preset: raw } });
    try {
      const emitter = document.querySelector<HTMLInputElement>("#pTrait-preset-1-emitter");
      expect(emitter?.checked).toBe(true);
      expect(emitter?.disabled).toBe(true);
      document.querySelector<HTMLButtonElement>("button.save")?.click();
      await vi.waitFor(() => {
        expect(savePreset).toHaveBeenCalledWith(
          expect.objectContaining({
            emitter: true,
            implements: false,
            reads_images: false,
            can_manage: false,
          }),
        );
      });
    } finally {
      await unmount(card);
    }
  });
});

describe("PresetCard compaction limit", () => {
  it("sends the override, and null when the field is blank", async () => {
    session.adapters = [adapter];
    const savePreset = vi.spyOn(api, "savePreset").mockResolvedValue(preset);
    vi.spyOn(session, "loadPresets").mockResolvedValue();
    const card = mount(PresetCard, {
      target: document.body,
      props: { preset: { ...preset, max_compactions: 3 } },
    });
    try {
      const field = document.querySelector<HTMLInputElement>("#pMaxCompactions-preset-1");
      expect(field?.value).toBe("3");
      if (!field) throw new Error("missing field");
      field.value = "0";
      field.dispatchEvent(new Event("input", { bubbles: true }));
      document.querySelector<HTMLButtonElement>("button.save")?.click();
      await vi.waitFor(() => {
        expect(savePreset).toHaveBeenLastCalledWith(expect.objectContaining({ max_compactions: 0 }));
      });
      await vi.waitFor(() => {
        expect(document.querySelector<HTMLButtonElement>("button.save")?.disabled).toBe(false);
      });
      field.value = "";
      field.dispatchEvent(new Event("input", { bubbles: true }));
      document.querySelector<HTMLButtonElement>("button.save")?.click();
      await vi.waitFor(() => {
        expect(savePreset).toHaveBeenLastCalledWith(expect.objectContaining({ max_compactions: null }));
      });
    } finally {
      void unmount(card);
    }
  });
});
