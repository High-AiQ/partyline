<script lang="ts">
  /** What Partyline keeps on disk, with a Clear button for the data it can recreate. */
  import { onMount } from "svelte";
  import StorageClearDialog from "./StorageClearDialog.svelte";
  import SettingRow from "../settings/SettingRow.svelte";
  import { ApiError } from "../../lib/api";
  import { humanSize } from "../../lib/files";
  import { storageApi, type StorageCategory } from "../../lib/storage-api";
  import { dialogs } from "../../state/dialogs.svelte";

  let categories = $state<StorageCategory[]>([]);
  let loading = $state(true);
  let error = $state("");

  async function load(): Promise<void> {
    loading = true;
    error = "";
    try {
      categories = await storageApi.list();
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not load storage";
    } finally {
      loading = false;
    }
  }
  onMount(() => void load());
</script>

<SettingRow
  id="setting-storage"
  label="Storage usage"
  description="Disk used by lines, media and worktrees. Clear removes only what Partyline can recreate, after a confirmation."
  stacked
>
  <div class="line-status" class:error={Boolean(error)} aria-live="polite">
    {loading ? "measuring…" : error}
  </div>
  <ul class="text-[12px] text-cream-dim">
    {#each categories as category (category.key)}
      <li
        class="flex items-center justify-between gap-2 border-b border-line/60 py-2 last:border-b-0"
        data-storage={category.key}
      >
        <span class="min-w-0 break-words">
          {category.label}: {category.approximate ? "≈ " : ""}{humanSize(category.bytes)}
          {#if category.clearable}
            · clearable {humanSize(category.clearable_bytes)} ({category.clearable_count})
          {/if}
        </span>
        {#if category.clearable}
          <button
            type="button"
            disabled={category.clearable_count === 0}
            onclick={() => dialogs.open(StorageClearDialog, { category, cleared: () => void load() })}
            >clear</button
          >
        {/if}
      </li>
    {/each}
  </ul>
  <button type="button" class="mt-1" onclick={() => void load()} disabled={loading}>refresh</button>
</SettingRow>
