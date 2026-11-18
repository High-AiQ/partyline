<script lang="ts">
  import { workflowApi, type WorkflowRun } from "../../lib/workflow-api";
  import { wire } from "../../state/wire.svelte.js";
  import { workflowRuns } from "../../state/workflow-runs.svelte.js";
  import WorkflowRunCard from "./WorkflowRunCard.svelte";

  interface Props {
    line: string;
  }

  let { line }: Props = $props();
  let runs = $state<WorkflowRun[]>([]);
  const active = $derived(runs.filter((run) => run.outcome === null));
  const latest = $derived(runs.find((run) => run.outcome !== null));
  const cards = $derived(latest ? [...active, latest] : active);
  const earlier = $derived(runs.filter((run) => run.outcome !== null && run !== latest));

  $effect(() => {
    if (!wire.ready) return;
    void workflowRuns.revision;
    const controller = new AbortController();
    void workflowApi
      .runs(line, controller.signal)
      .then((snapshot) => {
        if (!controller.signal.aborted) runs = snapshot.runs;
      })
      .catch(() => {
        // The next wire event or reconnect requests a fresh snapshot.
      });
    return () => {
      controller.abort();
    };
  });
</script>

{#if cards.length}
  <section
    aria-label="Screen workflow runs"
    class="max-h-[28dvh] shrink-0 overflow-y-auto border-t border-line bg-ink-2 px-3"
  >
    {#each cards as run (run.run_id)}
      <WorkflowRunCard {line} {run} />
    {/each}
    {#if earlier.length}
      <details class="py-2 text-xs text-cream-dim">
        <summary>Earlier workflow runs</summary>
        {#each earlier as run (run.run_id)}
          <WorkflowRunCard {line} {run} />
        {/each}
      </details>
    {/if}
  </section>
{/if}
