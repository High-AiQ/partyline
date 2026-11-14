<script lang="ts">
  import { turnLabel, turnUsageApi, type TurnSummary } from "../../lib/turn-usage-api";
  interface Props {
    convId: string;
  }
  let { convId }: Props = $props();
  let descendants = $state(false);
  let summary = $state<TurnSummary | null>(null);
  let error = $state("");
  let loading = $state(true);
  let revision = $state(0);

  $effect(() => {
    void revision;
    let cancelled = false;
    loading = true;
    error = "";
    void turnUsageApi
      .read(convId, descendants)
      .then((value) => {
        if (!cancelled) summary = value;
      })
      .catch((failure: unknown) => {
        if (!cancelled) error = failure instanceof Error ? failure.message : "could not load model usage";
      })
      .finally(() => {
        if (!cancelled) loading = false;
      });
    return () => {
      cancelled = true;
    };
  });
</script>

<section class="mt-5 min-w-0 border-t border-cream-ghost pt-4" aria-label="Model usage" data-turn-usage>
  <h3 class="text-sm font-semibold text-cream">Model usage</h3>
  <p class="dialog-note">
    Actual tokens per model response (input + cache + output) · last 30 days. A response counts in full for
    every tool it called, so compare it with the estimated result size above.
  </p>
  <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
    <label class="dialog-check"><input type="checkbox" bind:checked={descendants} /> include sublines</label>
    <button type="button" disabled={loading} onclick={() => revision++}>refresh model usage</button>
  </div>
  {#if loading}
    <p class="text-sm text-cream-faint" role="status">loading model usage…</p>
  {:else if error}
    <p class="text-sm text-pink" role="alert">{error}</p>
  {:else if summary?.totals.turns}
    <p class="mb-2 text-xs tabular-nums text-cream-faint" data-turn-totals>
      {summary.totals.turns.toLocaleString()} responses · {summary.totals.total_tokens.toLocaleString()} tokens
      ({summary.totals.cache_read_tokens.toLocaleString()} cache read ·
      {summary.totals.cache_write_tokens.toLocaleString()} cache write ·
      {summary.totals.output_tokens.toLocaleString()} output)
    </p>
    <table class="w-full table-fixed text-left text-xs tabular-nums">
      <caption class="sr-only">Model usage by tool, sorted by total tokens</caption>
      <thead class="text-cream-faint">
        <tr>
          <th class="w-1/2 pb-2 font-normal">tool / operation</th>
          <th class="pb-2 text-right font-normal">turns</th>
          <th class="pb-2 text-right font-normal">p50</th>
          <th class="pb-2 text-right font-normal">p95</th>
        </tr>
      </thead>
      <tbody>
        {#each summary.rows as row (`${row.tool}:${row.sub_op}`)}
          <tr class="border-t border-cream-ghost">
            <td class="break-words py-2 pr-2 align-top">{turnLabel(row)}</td>
            <td class="py-2 text-right align-top">{row.turns.toLocaleString()}</td>
            <td class="py-2 text-right align-top text-copper">{row.p50_total_tokens.toLocaleString()}</td>
            <td class="py-2 text-right align-top text-copper">{row.p95_total_tokens.toLocaleString()}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <ul class="mt-3 space-y-1 text-xs tabular-nums text-cream-faint" aria-label="Usage per process">
      {#each summary.attachments as item (item.attachment_id)}
        <li>
          {item.name ?? item.attachment_id.slice(0, 8)} · {item.adapter} · {item.turns.toLocaleString()} responses
          ·
          {item.total_tokens.toLocaleString()} tokens
        </li>
      {/each}
    </ul>
  {:else}
    <p class="text-sm text-cream-faint">No model usage recorded yet.</p>
  {/if}
</section>
