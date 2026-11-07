<script lang="ts">
  /** Light, dark, or the system's choice — saved in this browser the moment it changes. */
  import { onDestroy } from "svelte";
  import SettingsSection from "../SettingsSection.svelte";
  import SettingRow from "../SettingRow.svelte";
  import SaveIndicator from "../SaveIndicator.svelte";
  import { SaveTracker } from "../../../lib/save-state";
  import type { SaveSnapshot } from "../../../lib/save-state";
  import { theme } from "../../../state/theme.svelte.js";

  type Choice = "system" | "light" | "dark";
  const CHOICES: readonly { value: Choice; label: string }[] = [
    { value: "system", label: "system" },
    { value: "light", label: "light" },
    { value: "dark", label: "dark" },
  ];
  const choice = $derived<Choice>(theme.explicit ? theme.current : "system");
  let save = $state<SaveSnapshot>({ phase: "idle", message: "" });
  const tracker = new SaveTracker((next) => (save = next));
  onDestroy(() => {
    tracker.dispose();
  });

  function choose(next: Choice): void {
    void tracker.run(() => {
      if (next === "system") theme.followSystem();
      else theme.set(next);
      return Promise.resolve();
    });
  }
</script>

<SettingsSection id="appearance">
  <SettingRow
    id="setting-theme"
    label="Theme"
    description="Saved in this browser only. The sun and moon in the top bar switch it too."
  >
    <div role="radiogroup" aria-label="theme" class="inline-flex rounded border border-line bg-ink-3 p-0.5">
      {#each CHOICES as option (option.value)}
        <label
          class="flex min-h-9 cursor-pointer items-center rounded px-3 text-[11.5px] has-focus-visible:outline-2 has-focus-visible:outline-copper-hot {choice ===
          option.value
            ? 'bg-copper text-ink'
            : 'text-cream-dim hover:text-cream'}"
        >
          <input
            class="sr-only"
            type="radio"
            name="theme"
            value={option.value}
            checked={choice === option.value}
            onchange={() => {
              choose(option.value);
            }}
          />
          {option.label}
        </label>
      {/each}
    </div>
    {#snippet status()}<SaveIndicator
        state={save}
        idle={choice === "system" ? `following the system: ${theme.current}` : ""}
      />{/snippet}
  </SettingRow>
</SettingsSection>
