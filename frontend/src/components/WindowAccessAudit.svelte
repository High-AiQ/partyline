<script lang="ts">
  import { formatScreenAccessDetail, screenApi, type ScreenAccessEntry } from "../lib/screen-api";

  interface AuditLine {
    id: string;
    name: string;
  }

  let { lines, currentLine }: { lines: AuditLine[]; currentLine: string | null } = $props();
  let open = $state(false);
  let loading = $state(false);
  let selectedLine = $state("");
  let loadedLine = $state("");
  let entries = $state<ScreenAccessEntry[]>([]);
  let nextBefore = $state<number | null>(null);
  let error = $state("");
  const line = $derived(
    [selectedLine, currentLine].find((id) => lines.some((item) => item.id === id)) ?? lines[0]?.id ?? "",
  );
  const visible = $derived(open && !!line && loadedLine === line);
  const inputId = $props.id();

  async function load(id: string, before: number | null): Promise<void> {
    loadedLine = id;
    loading = true;
    error = "";
    if (before === null) {
      entries = [];
      nextBefore = null;
    }
    try {
      const audit = await screenApi.screenAccessAudit(id, before);
      entries = [...entries, ...audit.entries];
      nextBefore = audit.next_before;
    } catch {
      error = "Could not load the screen access log";
    } finally {
      loading = false;
    }
  }

  async function toggle(): Promise<void> {
    if (visible) {
      open = false;
    } else if (line) {
      selectedLine = line;
      open = true;
      await load(line, null);
    }
  }
</script>

{#if line}
  <div class="my-2">
    <button
      type="button"
      class="text-sm underline"
      aria-expanded={visible}
      aria-controls={inputId + "-panel"}
      onclick={() => void toggle()}
      disabled={loading}
    >
      {visible ? "Hide log" : "View log"}
    </button>
    {#if visible}
      <div class="mt-2 rounded border border-line p-2 text-xs" id={inputId + "-panel"}>
        <p class="font-semibold">Screen and window access log</p>
        <label class="mr-1" for={inputId}>Line</label>
        <select
          class="max-w-full"
          id={inputId}
          value={line}
          disabled={loading}
          onchange={(event) => {
            selectedLine = event.currentTarget.value;
            void load(selectedLine, null);
          }}
        >
          {#each lines as option (option.id)}
            <option value={option.id}>{option.name}</option>
          {/each}
        </select>
        {#if error}<p role="alert">{error}</p>{/if}
        {#if !loading && !error && entries.length === 0}<p>No screen access recorded for this line.</p>{/if}
        <div class="max-h-80 overflow-auto" aria-busy={loading}>
          {#each entries as entry (entry.entry_hash)}
            <article class="mt-2 border-t border-line pt-2">
              <p>
                <strong>{entry.agent}</strong>
                {#if entry.time > 0}
                  · {new Date(entry.time * 1000).toLocaleString()}{/if}
              </p>
              <p class="break-words whitespace-pre-wrap">{formatScreenAccessDetail(entry.detail)}</p>
              <details>
                <summary class="cursor-pointer">Audit chain</summary>
                <dl class="break-all text-[10px]">
                  <dt>Chain ID</dt>
                  <dd><code>{entry.chain_id}</code></dd>
                  <dt>Entry SHA-256</dt>
                  <dd><code>{entry.entry_hash}</code></dd>
                  {#if entry.previous_hash}
                    <dt>Previous SHA-256</dt>
                    <dd><code>{entry.previous_hash}</code></dd>
                  {/if}
                </dl>
              </details>
            </article>
          {/each}
          {#if nextBefore !== null}
            <button type="button" class="mt-2" disabled={loading} onclick={() => void load(line, nextBefore)}
              >Load older entries</button
            >
          {/if}
        </div>
        {#if loading}<p role="status">Loading…</p>{/if}
      </div>
    {/if}
  </div>
{/if}
