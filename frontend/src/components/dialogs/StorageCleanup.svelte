<script lang="ts">
  import { onMount } from "svelte";
  import SettingRow from "../settings/SettingRow.svelte";
  import { humanSize } from "../../lib/files";
  import { storageCleanupApi, type StorageCleanup, type StorageDetails } from "../../lib/storage-api";

  let { refreshed }: { refreshed: () => void } = $props();
  let inventory = $state<StorageDetails>({ kept: [], idle_lines: [] });
  let result = $state<StorageCleanup | null>(null);
  let busy = $state(false);
  let error = $state("");

  async function load(): Promise<void> {
    try {
      inventory = await storageCleanupApi.details();
    } catch (failure: unknown) {
      error = failure instanceof Error ? failure.message : "could not load storage details";
    }
  }
  onMount(() => void load());

  async function clean(): Promise<void> {
    busy = true;
    error = "";
    try {
      result = await storageCleanupApi.cleanup();
      refreshed();
      await load();
    } catch (failure: unknown) {
      error = failure instanceof Error ? failure.message : "could not clean up storage";
    } finally {
      busy = false;
    }
  }
</script>

<SettingRow
  id="setting-storage-cleanup"
  label="Automatic cleanup"
  description="On by default. Stopped processes shed recreatable caches. Retired and orphaned worktrees are removed after saving Git changes for recovery. Live processes and saved restarts are protected."
  stacked
>
  <button type="button" onclick={() => void clean()} disabled={busy}>
    {busy ? "Cleaning up…" : "Clean up now"}
  </button>
  <div class="line-status" class:error={Boolean(error)} aria-live="polite">
    {#if error}{error}{:else if result}
      Freed {humanSize(result.freed_bytes)} · removed {result.removed.length} items.
    {/if}
  </div>
  {#if result?.skipped.length}
    <details class="text-[12px] text-cream-dim">
      <summary>Kept {result.skipped.length} items</summary>
      <ul>
        {#each result.skipped as item (item.path)}
          <li class="break-words py-1">{item.path} · {humanSize(item.size_bytes)} — {item.reason}</li>
        {/each}
      </ul>
    </details>
  {/if}
  {#if inventory.kept.length}
    <details class="text-[12px] text-cream-dim">
      <summary>Kept worktrees and orphans ({inventory.kept.length})</summary>
      <ul>
        {#each inventory.kept as item (item.path)}
          <li class="break-words py-1">{item.path} · {humanSize(item.size_bytes)} — {item.reason}</li>
        {/each}
      </ul>
    </details>
  {/if}
  {#if inventory.idle_lines.length}
    <div class="text-[12px] text-cream-dim">
      <p>Open lines idle over 14 days · review when ready; these stay open.</p>
      <ul>
        {#each inventory.idle_lines as line (line.id)}
          <li class="py-1">{line.name} · {humanSize(line.size_bytes)}</li>
        {/each}
      </ul>
    </div>
  {/if}
</SettingRow>
