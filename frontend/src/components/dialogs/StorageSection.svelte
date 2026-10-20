<script lang="ts">
  /** What Partyline keeps on disk, with a Clear button for the data it can recreate. */
  import { onMount } from "svelte";
  import StorageClearDialog from "./StorageClearDialog.svelte";
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

<section class="mb-5 border-b border-line pb-4" aria-label="storage">
  <h2 class="mb-2 text-[12px] text-cream">storage</h2>
  <div class="line-status" class:error={Boolean(error)} aria-live="polite">
    {loading ? "measuring…" : error}
  </div>
  <ul class="text-[12px] text-cream-dim">
    {#each categories as category (category.key)}
      <li class="flex items-center justify-between gap-2 py-1" data-storage={category.key}>
        <span>
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
</section>
