<script lang="ts">
  import { toolUsage, usageLabel, type UsageSummary } from "../../lib/tool-usage-api";
  interface Props {
    convId: string;
  }
  let { convId }: Props = $props();
  let descendants = $state(false);
  let summary = $state<UsageSummary | null>(null);
  let error = $state("");
  let loading = $state(true);
  let revision = $state(0);

  $effect(() => {
    void revision;
    let cancelled = false;
    loading = true;
    error = "";
    void toolUsage(convId, descendants)
      .then((value) => {
        if (!cancelled) summary = value;
      })
      .catch((failure: unknown) => {
        if (!cancelled) error = failure instanceof Error ? failure.message : "could not load tool usage";
      })
      .finally(() => {
        if (!cancelled) loading = false;
      });
    return () => {
      cancelled = true;
    };
  });
</script>

<section class="mt-5 min-w-0 border-t border-line pt-4" aria-label="Usage">
  <h3 class="text-sm font-semibold text-cream">Usage</h3>
  <p class="dialog-note">
    Estimated tool result tokens · last 30 days · excludes model turns and tool inputs.
  </p>
  <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
    <label class="dialog-check"><input type="checkbox" bind:checked={descendants} /> include sublines</label>
    <button type="button" disabled={loading} onclick={() => revision++}>refresh usage</button>
  </div>
  {#if loading}
    <p class="text-sm text-cream-faint" role="status">loading usage…</p>
  {:else if error}
    <p class="text-sm text-pink" role="alert">{error}</p>
  {:else if summary?.rows.length}
    <table class="w-full table-fixed text-left text-xs tabular-nums">
      <caption class="sr-only">Tool usage sorted by total estimated tokens</caption>
      <thead class="text-cream-faint">
        <tr
          ><th class="w-1/2 pb-2 font-normal">tool / operation</th><th
            class="w-[15%] pb-2 text-right font-normal">calls</th
          ><th class="pb-2 text-right font-normal">est. tokens</th></tr
        >
      </thead>
      <tbody>
        {#each summary.rows as row (JSON.stringify( [row.tool, row.sub_op, row.action, row.then, row.refresh, row.query, row.more] ))}
          <tr class="border-t border-line">
            <td class="break-words py-2 pr-2 align-top">{usageLabel(row)}</td>
            <td class="py-2 text-right align-top">{row.calls.toLocaleString()}</td>
            <td class="py-2 text-right align-top text-copper"
              >{row.total_estimated_tokens.toLocaleString()}</td
            >
          </tr>
          <tr class="text-cream-faint"
            ><td colspan="3" class="pb-3">
              tokens p50 {row.p50_estimated_tokens.toLocaleString()} · p95 {row.p95_estimated_tokens.toLocaleString()}
              · max {row.max_estimated_tokens.toLocaleString()}<br />
              {row.errors} errors · latency p50 {Math.round(row.p50_latency_ms).toLocaleString()} ms
              {#if row.unknown_images}
                · {row.unknown_images} images with unknown token cost{/if}
            </td></tr
          >
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="text-sm text-cream-faint">No tool calls recorded yet.</p>
  {/if}
</section>
