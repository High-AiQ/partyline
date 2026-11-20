/** Shared labels and defaults for editable process-trait checkboxes. */

export const PRESET_TRAITS = [
  { key: "reads_images", label: "Reads images", defaultValue: false },
  { key: "can_manage", label: "Can manage a line", defaultValue: false },
  { key: "implements", label: "Fast implementer", defaultValue: true },
  { key: "emitter", label: "Emitter", defaultValue: false },
] as const;

export type PresetTraitKey = (typeof PRESET_TRAITS)[number]["key"];

export type PresetTraitValues = Record<PresetTraitKey, boolean>;
export type PresetTraitInput = Partial<Record<PresetTraitKey, boolean | undefined>>;

export function defaultPresetTraits(): PresetTraitValues {
  return {
    reads_images: false,
    can_manage: false,
    implements: true,
    emitter: false,
  };
}

export function isEmitter(process: { adapter: string; emitter?: boolean | undefined }): boolean {
  return process.adapter === "raw" || process.emitter === true;
}

export function traitsFrom(source: PresetTraitInput | undefined, adapter = ""): PresetTraitValues {
  if (isEmitter({ adapter, emitter: source?.emitter })) {
    return { reads_images: false, can_manage: false, implements: false, emitter: true };
  }
  const defaults = defaultPresetTraits();
  if (!source) return defaults;
  return {
    reads_images: source.reads_images ?? defaults.reads_images,
    can_manage: source.can_manage ?? defaults.can_manage,
    implements: source.implements ?? defaults.implements,
    emitter: false,
  };
}
