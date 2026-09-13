/** Shared labels and defaults for editable process-trait checkboxes. */

export const PRESET_TRAITS = [
  { key: "reads_images", label: "Reads images", defaultValue: false },
  { key: "can_manage", label: "Can manage a line", defaultValue: false },
  { key: "implements", label: "Fast implementer", defaultValue: true },
] as const;

export type PresetTraitKey = (typeof PRESET_TRAITS)[number]["key"];

export type PresetTraitValues = Record<PresetTraitKey, boolean>;

export function defaultPresetTraits(): PresetTraitValues {
  return {
    reads_images: false,
    can_manage: false,
    implements: true,
  };
}

export function traitsFrom(source: Partial<PresetTraitValues> | undefined): PresetTraitValues {
  const defaults = defaultPresetTraits();
  if (!source) return defaults;
  return {
    reads_images: source.reads_images ?? defaults.reads_images,
    can_manage: source.can_manage ?? defaults.can_manage,
    implements: source.implements ?? defaults.implements,
  };
}
