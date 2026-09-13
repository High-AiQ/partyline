import { describe, expect, it } from "vitest";
import { PresetSchema, StaffingSchema } from "./preset-contracts";
import { defaultPresetTraits, traitsFrom } from "./preset-traits";

describe("preset trait contracts", () => {
  it("defaults omitted trait fields so old payloads still parse", () => {
    const preset = PresetSchema.parse({
      id: "p1",
      title: "grok",
      name: "grok",
      adapter: "grok",
      command: "grok",
      created_at: 1,
    });
    expect(preset.reads_images).toBe(false);
    expect(preset.can_manage).toBe(false);
    expect(preset.implements).toBe(true);
  });

  it("keeps explicit trait flags", () => {
    const preset = PresetSchema.parse({
      id: "p1",
      title: "captain",
      name: "sol",
      adapter: "codex",
      command: "codex",
      created_at: 1,
      reads_images: true,
      can_manage: true,
      implements: false,
    });
    expect(preset.reads_images).toBe(true);
    expect(preset.can_manage).toBe(true);
    expect(preset.implements).toBe(false);
  });

  it("parses a staffing snapshot with unmatched processes", () => {
    const staffing = StaffingSchema.parse({
      presets_in_use: false,
      presets: [
        {
          id: "p1",
          title: "grok",
          name: "grok",
          adapter: "grok",
          reads_images: false,
          can_manage: false,
          implements: true,
        },
      ],
      processes: [
        {
          line_id: "line",
          line: "work",
          handle: "grok-2",
          adapter: "grok",
          captain: false,
          matched_preset: null,
          traits: null,
        },
      ],
    });
    expect(staffing.processes[0]?.matched_preset).toBeNull();
  });
});

describe("preset trait helpers", () => {
  it("fills defaults when a draft omits flags", () => {
    expect(traitsFrom(undefined)).toEqual(defaultPresetTraits());
    expect(traitsFrom({ reads_images: true }).can_manage).toBe(false);
    expect(traitsFrom({ implements: false }).implements).toBe(false);
  });
});
