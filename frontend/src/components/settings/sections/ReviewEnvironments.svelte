<script lang="ts">
  import { onMount } from "svelte";
  import { z } from "zod";
  import SettingRow from "../SettingRow.svelte";
  import { request } from "../../../lib/http";

  const Entry = z.object({
    repository: z.string(),
    subpath: z.string(),
    setup_command: z.string(),
    test_command: z.string(),
    set_by: z.string(),
    set_at: z.number(),
  });
  const Listing = z.object({ entries: z.array(Entry) });
  type Entry = z.infer<typeof Entry>;
  let entries = $state<Entry[]>([]);
  let status = $state("loading…");
  let busy = $state(true);
  onMount(() => {
    request("/api/settings/review-environments", { schema: Listing })
      .then((result) => {
        entries = result.entries;
        status = "";
      })
      .catch((error: unknown) => {
        status = error instanceof Error ? error.message : "could not load";
      })
      .finally(() => {
        busy = false;
      });
  });
  async function save(): Promise<void> {
    busy = true;
    try {
      const result = await request("/api/settings/review-environments", {
        schema: Listing,
        method: "PUT",
        body: { entries },
      });
      entries = result.entries;
      status = "saved";
    } catch (error: unknown) {
      status = error instanceof Error ? error.message : "could not save";
    } finally {
      busy = false;
    }
  }
</script>

<SettingRow
  id="setting-review-environments"
  label="Review environments"
  stacked
  description="Optional per-repository setup and test commands for managed review checkouts. Empty setup uses the nearest supported lockfile."
>
  <div class="flex flex-col gap-3">
    {#each entries as entry, index (entry)}
      <div class="flex flex-col gap-2 rounded border border-line p-3">
        {#if entry.set_by}<p>Set by {entry.set_by} · {new Date(entry.set_at * 1000).toLocaleString()}</p>{/if}
        <label>Repository URL or absolute path <input class="w-full" bind:value={entry.repository} /></label>
        <label>Subpath <input class="w-full" bind:value={entry.subpath} placeholder="." /></label>
        <label
          >Setup command <input
            class="w-full"
            bind:value={entry.setup_command}
            placeholder="use lockfile default"
          /></label
        >
        <label
          >Test command <input class="w-full" bind:value={entry.test_command} placeholder="optional" /></label
        >
        <button
          type="button"
          onclick={() => {
            entries = entries.filter((_, i) => i !== index);
          }}>remove</button
        >
      </div>
    {/each}
    <div class="flex gap-2">
      <button
        type="button"
        disabled={busy}
        onclick={() => {
          entries = [
            ...entries,
            { repository: "", subpath: ".", setup_command: "", test_command: "", set_by: "", set_at: 0 },
          ];
        }}>add environment</button
      >
      <button type="button" class="primary" disabled={busy} onclick={save}>save environments</button>
    </div>
    <p class="line-status" aria-live="polite">{status}</p>
  </div>
</SettingRow>
