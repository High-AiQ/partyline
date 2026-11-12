<script lang="ts">
  /** Attach presets (edited in place), installed adapters with import, and task-history cleanup. */
  import SettingsSection from "../SettingsSection.svelte";
  import SettingRow from "../SettingRow.svelte";
  import PresetCard from "../../dialogs/PresetCard.svelte";
  import ImportAdaptersDialog from "../../dialogs/ImportAdaptersDialog.svelte";
  import TaskHistorySetting from "../../dialogs/TaskHistorySetting.svelte";
  import MaxCompactionsSetting from "../../dialogs/MaxCompactionsSetting.svelte";
  import { adapterLabel } from "../../../lib/attachments";
  import { dialogs } from "../../../state/dialogs.svelte.js";
  import { session } from "../../../state/session.svelte.js";
</script>

<SettingsSection id="processes">
  <SettingRow
    id="setting-process-presets"
    label="Process presets"
    description="Saved attach forms. Create one from the attach form on any line with save; edit or delete it here."
    stacked
  >
    {#if session.presets.length}
      <div class="flex flex-col gap-3">
        {#each session.presets as preset (preset.id)}
          <PresetCard {preset} />
        {/each}
      </div>
    {:else}
      <p class="dialog-note">no presets yet — fill the attach form and hit save</p>
    {/if}
  </SettingRow>
  <SettingRow
    id="setting-adapters"
    label="Adapters"
    description="How Partyline drives each CLI. Imported adapters are code that runs as you: review a repository before importing it."
  >
    <button type="button" onclick={() => dialogs.open(ImportAdaptersDialog)}>import adapters…</button>
    {#snippet status()}
      <ul class="flex flex-wrap gap-1.5" aria-label="installed adapters">
        {#each session.adapters as adapter (adapter.id)}
          <li class="rounded border border-line px-2 py-0.5 text-[10.5px] text-cream-dim">
            {adapterLabel(adapter.id)}{adapter.version ? ` ${adapter.version}` : ""}
          </li>
        {/each}
      </ul>
    {/snippet}
  </SettingRow>
  <TaskHistorySetting />
  <MaxCompactionsSetting />
</SettingsSection>
