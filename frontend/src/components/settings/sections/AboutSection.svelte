<script lang="ts">
  /** Which release, bundle and commit this server runs — copyable for a bug report. */
  import { onMount } from "svelte";
  import SettingsSection from "../SettingsSection.svelte";
  import SettingRow from "../SettingRow.svelte";
  import { aboutApi } from "../../../lib/about-api";
  import type { About } from "../../../lib/about-api";
  import { copyText } from "../../../lib/clipboard";

  let about = $state<About | null>(null);
  let error = $state("");
  let copied = $state("");
  onMount(() => {
    aboutApi
      .about()
      .then((value) => (about = value))
      .catch((failure: unknown) => (error = failure instanceof Error ? failure.message : "could not load"));
  });
  const facts = $derived<[string, string][]>(
    about
      ? [
          ["version", about.version],
          ["frontend build", about.build],
          ["git head", about.git_head ?? "unknown"],
          ["checkout", about.checkout_path ?? "unknown"],
          ["instance", about.instance_name ?? "not set"],
        ]
      : [],
  );

  async function copy(): Promise<void> {
    const text = facts.map(([key, value]) => `${key}: ${value}`).join("\n");
    copied = (await copyText(text)) ? "copied ✓" : "could not copy";
  }
</script>

<SettingsSection id="about">
  <SettingRow
    id="setting-version"
    label="Version and build"
    description="What this server is running."
    stacked
  >
    <p class="line-status error" aria-live="polite">{error}</p>
    <dl class="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[12px]">
      {#each facts as [key, value] (key)}
        <dt class="text-cream-faint">{key}</dt>
        <dd class="min-w-0 font-mono break-all text-cream" data-about={key}>{value}</dd>
      {/each}
    </dl>
    {#snippet status()}
      <div class="flex items-center gap-3">
        <button type="button" disabled={!about} onclick={() => void copy()}>copy details</button>
        <span class="text-[10.5px] text-green" aria-live="polite">{copied}</span>
      </div>
    {/snippet}
  </SettingRow>
</SettingsSection>
