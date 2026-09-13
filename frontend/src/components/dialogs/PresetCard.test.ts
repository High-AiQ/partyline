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
  it("shows the three trait checkboxes on a manage card", () => {
    session.adapters = [adapter];
    const card = mount(PresetCard, { target: document.body, props: { preset } });
    try {
      expect(document.querySelector("#pTrait-preset-1-reads_images")).toBeInstanceOf(HTMLInputElement);
      expect(document.querySelector("#pTrait-preset-1-can_manage")).toBeInstanceOf(HTMLInputElement);
      expect(document.querySelector("#pTrait-preset-1-implements")).toBeInstanceOf(HTMLInputElement);
      expect(document.body.textContent).toContain("Reads images");
      expect(document.body.textContent).toContain("Can manage a line");
      expect(document.body.textContent).toContain("Fast implementer");
    } finally {
      void unmount(card);
    }
  });

  it("includes the three trait flags on the save payload", async () => {
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
        });
      });
    } finally {
      void unmount(card);
    }
  });
});
