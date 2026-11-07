<script lang="ts">
  /** Feature flags, read-only: they are deployment decisions made in the config file or environment. */
  import { onMount } from "svelte";
  import SettingsSection from "../SettingsSection.svelte";
  import SettingRow from "../SettingRow.svelte";
  import { aboutApi } from "../../../lib/about-api";
  import type { FeatureFlag } from "../../../lib/about-api";

  let flags = $state<FeatureFlag[]>([]);
  let error = $state("");
  let loading = $state(true);
  onMount(() => {
    aboutApi
      .features()
      .then((list) => (flags = list))
      .catch((failure: unknown) => (error = failure instanceof Error ? failure.message : "could not load"))
      .finally(() => (loading = false));
  });
</script>

<SettingsSection id="advanced">
  <SettingRow
    id="setting-feature-flags"
    label="Feature flags"
    description="Read-only here. Switch one with PARTYLINE_FEATURE_<NAME>=on|off or a [features] table in the config file, then restart the server."
    stacked
  >
    <p class="line-status" class:error={Boolean(error)} aria-live="polite">{loading ? "loading…" : error}</p>
    <ul class="flex flex-col gap-2">
      {#each flags as flag (flag.name)}
        <li
          class="flex min-w-0 items-start gap-3 rounded border border-line px-3 py-2.5"
          data-flag={flag.name}
        >
          <span class="led mt-1.5 {flag.enabled ? 'running' : ''}" aria-hidden="true"></span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <code class="text-[12px] text-cream">{flag.name}</code>
              <span class="text-[10.5px] {flag.enabled ? 'text-green' : 'text-cream-faint'}"
                >{flag.enabled ? "on" : "off"}</span
              >
              <span
                class="rounded border border-line px-1.5 text-[9.5px] tracking-[0.05em] text-cream-dim uppercase"
                >{flag.status}</span
              >
              {#if flag.enabled !== flag.default}<span class="text-[10px] text-copper"
                  >changed from default</span
                >{/if}
            </div>
            <p class="mt-1 text-[11px] leading-[1.5] break-words text-cream-dim">{flag.summary}</p>
          </div>
        </li>
      {/each}
    </ul>
  </SettingRow>
</SettingsSection>
