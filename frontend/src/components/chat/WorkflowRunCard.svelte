<script lang="ts">
  import { workflowApi, WorkflowParametersSchema, type WorkflowRun } from "../../lib/workflow-api";
  import { workflowRuns } from "../../state/workflow-runs.svelte.js";

  interface Props {
    line: string;
    run: WorkflowRun;
  }

  let { line, run }: Props = $props();
  let busy = $state(false);
  let error = $state("");
  let needsParameters = $state(false);
  let parameters = $state("");
  let decidedToken = $state<string>();
  const confirmation = $derived(run.confirmation?.token !== decidedToken ? run.confirmation : undefined);
  const step = $derived(Math.min(run.verified_steps + 1, run.total_steps));
  const button = "min-h-8 px-2 py-1 text-xs disabled:opacity-50";

  async function decide(allow: boolean): Promise<void> {
    const pending = confirmation;
    if (!pending || busy) return;
    busy = true;
    error = "";
    try {
      await workflowApi.decide(line, run.run_id, pending.token, allow);
      decidedToken = pending.token;
    } catch (failure) {
      error = failure instanceof Error ? failure.message : "Could not send the confirmation";
    } finally {
      busy = false;
      workflowRuns.changed();
    }
  }

  async function resume(): Promise<void> {
    if (busy) return;
    if (run.needs_parameters && !needsParameters) {
      needsParameters = true;
      return;
    }
    busy = true;
    error = "";
    try {
      const original = needsParameters ? WorkflowParametersSchema.parse(JSON.parse(parameters)) : undefined;
      await workflowApi.resume(line, run.run_id, original);
      parameters = "";
      needsParameters = false;
    } catch (failure) {
      error = failure instanceof Error ? failure.message : "Could not resume the run";
    } finally {
      busy = false;
      workflowRuns.changed();
    }
  }
</script>

<article class="grid gap-2 border-b border-line py-2 text-xs last:border-b-0" aria-label={run.workflow}>
  <div class="flex flex-wrap items-center gap-x-2 gap-y-1" aria-live="polite">
    <strong class="min-w-0 [overflow-wrap:anywhere] text-cream">{run.workflow}</strong>
    <span class="min-w-0 [overflow-wrap:anywhere] text-cream-dim">
      {#if run.state === "completed"}
        Completed · {run.total_steps} steps verified
      {:else if run.outcome}
        Stopped at step {step} of {run.total_steps} · {run.current_step ?? run.state}
      {:else}
        Step {step} of {run.total_steps} · {run.current_step ?? "Starting"}
      {/if}
    </span>
    {#if run.resumable}
      <button class={button} type="button" disabled={busy} onclick={() => void resume()}>Resume</button>
    {/if}
  </div>
  {#if run.outcome && run.state !== "completed"}
    <p class="text-cream-dim">{run.outcome}</p>
  {/if}
  {#if confirmation}
    <div class="flex flex-wrap items-center justify-between gap-2 rounded border border-copper/40 p-2">
      <div class="min-w-0 [overflow-wrap:anywhere]">
        <p class="font-semibold text-cream">{confirmation.effect}</p>
        <p class="text-cream-dim">Confirm within 2 minutes</p>
        <details class="mt-1 text-cream-dim">
          <summary>Action details</summary>
          <pre class="whitespace-pre-wrap [overflow-wrap:anywhere]">{JSON.stringify(
              { action: confirmation.action, target: confirmation.target, inputs: confirmation.inputs },
              null,
              2,
            )}</pre>
        </details>
      </div>
      <div class="flex gap-2">
        <button class="{button} text-emerald" type="button" disabled={busy} onclick={() => void decide(true)}>
          Confirm
        </button>
        <button class={button} type="button" disabled={busy} onclick={() => void decide(false)}>Cancel</button
        >
      </div>
    </div>
  {/if}
  {#if run.resumable && needsParameters}
    <label class="grid gap-1">
      Original parameters (JSON)
      <textarea class="rounded border border-line bg-ink p-2 font-mono" rows="2" bind:value={parameters}
      ></textarea>
    </label>
  {/if}
  {#if error}<p role="alert" class="text-red">{error}</p>{/if}
</article>
