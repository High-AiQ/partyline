<script lang="ts">
  /** Shared process-trait checkboxes. */
  import {
    PRESET_TRAITS,
    traitsFrom,
    type PresetTraitKey,
    type PresetTraitValues,
  } from "../lib/preset-traits";

  interface Props {
    traits: PresetTraitValues;
    idPrefix?: string;
    adapter?: string;
    emitterOnly?: boolean;
  }

  // `$bindable()` marks the prop for parent binding; it is not a fallback.
  // eslint-disable-next-line @typescript-eslint/no-useless-default-assignment -- Svelte bindable marker
  let { traits = $bindable(), idPrefix = "trait", adapter = "", emitterOnly = false }: Props = $props();

  const locked = $derived(emitterOnly || adapter === "raw");
  const effective = $derived(traitsFrom(locked ? { emitter: true } : traits, adapter));

  function setTrait(key: PresetTraitKey, checked: boolean): void {
    traits = traitsFrom({ ...traits, [key]: checked });
  }
</script>

<div class="flex flex-col" data-process-traits>
  {#each PRESET_TRAITS as trait (trait.key)}
    <label
      class="flex items-center gap-2 min-h-11 cursor-pointer text-[10px] tracking-[0.05em] text-cream-faint"
      for="{idPrefix}-{trait.key}"
    >
      {trait.label}
      <input
        id="{idPrefix}-{trait.key}"
        class="h-[15px] w-[15px] flex-none p-0 accent-copper"
        type="checkbox"
        checked={effective[trait.key]}
        disabled={locked || (effective.emitter && trait.key !== "emitter")}
        onchange={(event) => {
          setTrait(trait.key, event.currentTarget.checked);
        }}
      />
    </label>
  {/each}
</div>
