<script lang="ts">
  import {
    computerUsage,
    type ComputerUsePeriod,
    type ComputerUseSummary,
  } from "../../lib/computer-usage-api";
  import { tooltip } from "../../lib/tooltip";

  interface Props {
    convId: string;
  }
  let { convId }: Props = $props();
  let period = $state<ComputerUsePeriod>("all");
  let descendants = $state(false);
  let summary = $state<ComputerUseSummary | null>(null);
  let hasComputerUse = $state(false);
  let expanded = $state(false);
  let error = $state("");
  let loading = $state(true);

  $effect(() => {
    let cancelled = false;
    loading = true;
    error = "";
    void computerUsage(convId, period, descendants)
      .then((value) => {
        if (cancelled) return;
        summary = value;
        if (value.responses > 0 || value.calls > 0) hasComputerUse = true;
      })
      .catch((failure: unknown) => {
        if (!cancelled) error = failure instanceof Error ? failure.message : "could not load computer use";
      })
      .finally(() => {
        if (!cancelled) loading = false;
      });
    return () => {
      cancelled = true;
    };
  });

  function duration(milliseconds: number): string {
    if (milliseconds < 1000) return `${Math.round(milliseconds).toLocaleString()} ms`;
    if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} s`;
    return `${(milliseconds / 60_000).toFixed(1)} min`;
  }
</script>

{#if (!summary && (loading || error)) || hasComputerUse}
  <section class="mt-5 min-w-0 border-t border-line pt-4" aria-label="Computer use" data-computer-usage>
    <h3 class="text-sm font-semibold text-cream">Computer use</h3>
    {#if !summary}
      {#if loading}
        <p class="dialog-note" role="status">loading computer use…</p>
      {:else if error}
        <p class="text-sm text-pink" role="alert">{error}</p>
      {/if}
    {:else if summary}
      <details class="mt-1 text-sm" data-computer-details bind:open={expanded}>
        <summary class="cursor-pointer text-cream-faint">
          {#if summary.responses > 0 || summary.calls > 0}
            {summary.responses.toLocaleString()}
            {summary.responses === 1 ? "response" : "responses"} ·
            {summary.total_tokens.toLocaleString()} tokens · {summary.actions.toLocaleString()}
            {summary.actions === 1 ? "action" : "actions"} · {summary.reads.toLocaleString()}
            {summary.reads === 1 ? "read" : "reads"}
          {:else}
            No computer use in this period
          {/if}
        </summary>
        {#if loading}
          <p class="dialog-note" role="status">updating computer use…</p>
        {/if}
        {#if error}
          <p class="text-sm text-pink" role="alert">{error}</p>
        {/if}
        <div class="my-3 flex flex-wrap items-end gap-3">
          <label class="grid gap-1 text-xs text-cream-faint" for="computerUsePeriod">
            period
            <select id="computerUsePeriod" bind:value={period}>
              <option value="hour">last hour</option>
              <option value="today">today</option>
              <option value="all">since line started</option>
            </select>
          </label>
          <label class="dialog-check mb-2">
            <input type="checkbox" bind:checked={descendants} /> include sublines
          </label>
        </div>
        <dl class="space-y-2 text-xs tabular-nums text-cream-faint">
          <div>
            <dt class="inline font-medium text-cream">Model tokens:</dt>
            <dd class="inline">
              {summary.total_tokens.toLocaleString()} total · {summary.input_tokens.toLocaleString()} input ·
              <span
                data-cache-tokens
                use:tooltip={{
                  label: `${summary.cache_read_tokens.toLocaleString()} cache read + ${summary.cache_write_tokens.toLocaleString()} cache write`,
                }}
              >
                {(summary.cache_read_tokens + summary.cache_write_tokens).toLocaleString()} cached
              </span>
              · {summary.output_tokens.toLocaleString()} output
            </dd>
          </div>
          <div>
            <dt class="inline font-medium text-cream">Images sent:</dt>
            <dd class="inline">
              {summary.images.toLocaleString()} · {summary.image_tokens.toLocaleString()} estimated image tokens
              {#if summary.images_with_unknown_tokens}
                · {summary.images_with_unknown_tokens.toLocaleString()} with unknown token estimates
              {/if}
            </dd>
          </div>
          <div>
            <dt class="inline font-medium text-cream">Time:</dt>
            <dd class="inline">
              {duration(summary.model_ms)} model thinking ({summary.model_time_responses.toLocaleString()} measured)
              · {duration(summary.tool_ms)} in screen tools
            </dd>
          </div>
          <div>
            <dt class="inline font-medium text-cream">Between actions (includes pauses):</dt>
            <dd class="inline">
              {#if summary.p50_action_ms !== null && summary.p95_action_ms !== null}
                p50 {duration(summary.p50_action_ms)} · p95 {duration(summary.p95_action_ms)} ·
                {summary.action_intervals.toLocaleString()} intervals
              {:else}
                needs two consecutive actions
              {/if}
            </dd>
          </div>
          <div>
            <dt class="inline font-medium text-cream">Errors / refusals:</dt>
            <dd class="inline">
              {summary.errors.toLocaleString()}
              {#if summary.unconfirmed}
                · {summary.unconfirmed.toLocaleString()} unconfirmed
              {/if}
              {#if summary.outcome_unknown}
                · {summary.outcome_unknown.toLocaleString()} legacy outcomes unknown
              {/if}
            </dd>
          </div>
        </dl>
        <p class="dialog-note mt-3" data-computer-basis use:tooltip={{ label: summary.basis }}>
          Model tokens count once per computer-use response. Image tokens are estimates; retained history
          covers about 30 days.
        </p>
      </details>
    {/if}
  </section>
{/if}
