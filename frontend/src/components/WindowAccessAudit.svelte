<script lang="ts">
  import { screenApi, type ScreenDevice, type WindowAccessEntry } from "../lib/screen-api";

  let { device }: { device: ScreenDevice } = $props();
  let open = $state(false);
  let loading = $state(false);
  let loadedLine = $state<string | null>(null);
  let entries = $state<WindowAccessEntry[]>([]);
  let chainHead = $state<string | null>(null);
  let error = $state("");
  const visible = $derived(open && loadedLine === device.window_access_line);

  async function toggle(): Promise<void> {
    if (visible) {
      open = false;
      return;
    }
    const line = device.window_access_line;
    if (!line) return;
    open = true;
    loading = true;
    loadedLine = line;
    entries = [];
    chainHead = null;
    error = "";
    try {
      const audit = await screenApi.windowAccessAudit(line);
      entries = audit.entries;
      chainHead = audit.chain_head;
    } catch {
      error = "Could not load the window access log";
    } finally {
      loading = false;
    }
  }

  function formatTime(time: number): string {
    return new Date(time * 1000).toLocaleString();
  }
</script>

<div class="my-2">
  {#if device.window_access_line}
    <button type="button" class="text-sm underline" onclick={() => void toggle()} disabled={loading}>
      {visible ? "Hide log" : "View log"}
    </button>
  {/if}
  {#if visible}
    <div class="mt-2 max-h-80 overflow-auto rounded border border-ink/20 p-2 text-xs">
      <p class="font-semibold">Window access audit · newest 50</p>
      {#if loading}<p>Loading…</p>{/if}
      {#if error}<p role="alert">{error}</p>{/if}
      {#if !loading && !error && entries.length === 0}<p>
          No window access calls recorded for this line.
        </p>{/if}
      {#each entries as entry (entry.entry_hash)}
        <article class="mt-2 border-t border-ink/10 pt-2">
          <p><strong>{entry.call}</strong> · {entry.result} · {entry.agent}</p>
          <p>{entry.app} · {entry.title}</p>
          <p>{formatTime(entry.time)}</p>
          <code class="break-all text-[10px]">sha256: {entry.entry_hash}</code>
        </article>
      {/each}
      {#if chainHead}<p class="mt-2 break-all text-[10px]">Chain head: <code>{chainHead}</code></p>{/if}
    </div>
  {/if}
</div>
