<script lang="ts">
  import Modal from "../Modal.svelte";
  import WorkflowReviewTree from "./WorkflowReviewTree.svelte";
  import {
    workflowApi,
    type WorkflowLearning,
    type WorkflowListing,
    type WorkflowReview,
    workflowPreviewIsClean,
    workflowPreviewLabel,
  } from "../../lib/workflow-api";
  interface Props {
    line: string;
    close: () => void;
  }

  let { line, close }: Props = $props();
  let workflows = $state<WorkflowListing[]>([]);
  let learning = $state<WorkflowLearning>({ demonstrations: [], drafts: [] });
  let review = $state<WorkflowReview>();
  let busy = $state(true);
  let error = $state("");
  let windowGrant = $state("");
  let historyFrom = $state("");
  let historyTo = $state("");
  let narrationText = $state("");
  let recording = $derived(learning.demonstrations.find((item) => item.state === "recording"));
  async function load(): Promise<void> {
    const [catalog, evidence] = await Promise.all([workflowApi.list(line), workflowApi.learning(line)]);
    workflows = catalog.workflows;
    learning = evidence;
  }

  async function handle(operation: () => Promise<void>): Promise<void> {
    busy = true;
    error = "";
    try {
      await operation();
    } catch (failure) {
      error = failure instanceof Error ? failure.message : "Could not update workflows";
    } finally {
      busy = false;
    }
  }

  $effect(() => {
    void handle(load);
  });
  function show(name: string): void {
    review = undefined;
    void handle(async () => {
      review = await workflowApi.review(line, name);
    });
  }

  function decide(current: WorkflowReview): void {
    void handle(async () => {
      if (current.approved) await workflowApi.revoke(line, current.name);
      else await workflowApi.approve(line, current.name, current.revision);
      review = await workflowApi.review(line, current.name);
      await load();
    });
  }

  function startRecording(): void {
    void handle(async () => {
      await workflowApi.startDemonstration(line, windowGrant.trim());
      windowGrant = "";
      await load();
    });
  }

  function stopRecording(id: string): void {
    void handle(async () => {
      await workflowApi.stopDemonstration(line, id);
      await load();
    });
  }

  function addNarration(id: string): void {
    void handle(async () => {
      await workflowApi.narrateDemonstration(line, id, narrationText.trim());
      narrationText = "";
      await load();
    });
  }

  function importHistory(): void {
    void handle(async () => {
      await workflowApi.historyDemonstration(
        line,
        windowGrant.trim(),
        new Date(historyFrom).getTime() / 1000,
        new Date(historyTo).getTime() / 1000,
      );
      await load();
    });
  }
</script>

<Modal title="Screen workflows" {close} wide>
  {#if error}<p role="alert" class="text-sm text-red">{error}</p>{/if}
  {#if !workflows.length}
    <p class="text-sm text-cream-dim">
      {busy ? "Loading workflows…" : "No workflows available on this line."}
    </p>
  {:else}
    <ul aria-label="Workflow definitions" class="grid gap-1">
      {#each workflows as workflow (workflow.name)}
        <li class="flex flex-wrap items-center justify-between gap-2 rounded border border-line px-3 py-2">
          <div class="min-w-0">
            <p class="text-sm font-semibold [overflow-wrap:anywhere]">{workflow.name}</p>
            <p class="text-xs text-cream-dim">
              {"error" in workflow
                ? workflow.error
                : `${workflow.approved ? "Approved" : "Needs approval"} · ${workflow.description}`}
            </p>
          </div>
          {#if !("error" in workflow)}
            <button
              type="button"
              class="min-h-9 px-2 text-xs"
              disabled={busy}
              onclick={() => {
                show(workflow.name);
              }}
            >
              Review <span class="sr-only">{workflow.name}</span>
            </button>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
  <section aria-label="Demonstration recording" class="mt-4 grid gap-2 rounded border border-line p-3">
    <h3 class="font-serif text-lg text-cream">Record a demonstration</h3>
    <label for="demonstrationGrant" class="text-xs text-cream-dim">Window grant ID</label>
    <div class="flex flex-wrap gap-2">
      <input id="demonstrationGrant" bind:value={windowGrant} class="min-w-0 flex-1" placeholder="grant ID" />
      <button
        type="button"
        class="min-h-9 px-3 text-xs"
        disabled={busy || !!recording || !windowGrant.trim()}
        onclick={startRecording}>Start</button
      >
    </div>
    <p class="text-xs text-cream-dim">Or build an unresolved draft source from a history interval:</p>
    <div class="flex flex-wrap items-end gap-2">
      <label class="grid gap-1 text-xs text-cream-dim"
        >From
        <input type="datetime-local" bind:value={historyFrom} />
      </label>
      <label class="grid gap-1 text-xs text-cream-dim"
        >To
        <input type="datetime-local" bind:value={historyTo} />
      </label>
      <button
        type="button"
        class="min-h-9 px-3 text-xs"
        disabled={busy || !windowGrant.trim() || !historyFrom || !historyTo}
        onclick={importHistory}>Import interval</button
      >
    </div>
    {#if recording}
      <p class="text-xs text-cream-dim">Recording {recording.id}</p>
      <label for="demonstrationNarration" class="text-xs text-cream-dim">Narration</label>
      <div class="flex flex-wrap gap-2">
        <input
          id="demonstrationNarration"
          bind:value={narrationText}
          class="min-w-0 flex-1"
          placeholder="Describe this step"
        />
        <button
          type="button"
          class="min-h-9 px-3 text-xs"
          disabled={busy || !narrationText.trim()}
          onclick={() => {
            addNarration(recording.id);
          }}>Add narration</button
        >
        <button
          type="button"
          class="min-h-9 px-3 text-xs"
          disabled={busy}
          onclick={() => {
            stopRecording(recording.id);
          }}>Stop</button
        >
      </div>
    {/if}
  </section>
  {#if learning.demonstrations.length || learning.drafts.length}
    <section aria-label="Workflow learning review" class="mt-4 grid gap-2">
      <h3 class="font-serif text-lg text-cream">Demonstrations and drafts</h3>
      {#each learning.demonstrations as demonstration (demonstration.id)}
        {@const draft = learning.drafts.find((item) => item.demonstration_id === demonstration.id)}
        <article class="grid gap-2 rounded border border-line p-3">
          <p class="text-xs text-cream-dim">Demonstration {demonstration.id} · {demonstration.state}</p>
          <ol class="grid gap-1 pl-5 text-xs">
            {#each demonstration.calls as call (call.index)}
              <li>
                <span class="font-mono">{new Date(call.at * 1000).toLocaleTimeString()} {call.operation}</span
                >
                · {call.outcome}
                {#if call.arguments}<pre
                    class="overflow-auto whitespace-pre-wrap text-cream-dim">{JSON.stringify(
                      call.arguments,
                    )}</pre>{/if}
                {#if call.observation}<p class="text-cream-dim">
                    Targets: {JSON.stringify(call.observation)}
                  </p>{/if}
                {#if call.unresolved}<p class="text-copper">Unresolved: {call.unresolved}</p>{/if}
              </li>
            {/each}
          </ol>
          <ul aria-label="Timed narration" class="grid gap-1 text-xs text-cream-dim">
            {#each demonstration.narration as line (line.index)}
              <li>
                {#if line.at !== null}[{new Date(line.at * 1000).toLocaleTimeString()}]{:else}[time
                  unavailable]{/if}
                “{line.text}”
              </li>
            {/each}
          </ul>
          {#if draft}
            <div class="border-t border-line pt-2">
              <p class="text-sm font-semibold">
                Draft: {draft.name} ·
                {draft.current ? (draft.approved ? "approved" : "unapproved") : "workflow changed"}
              </p>
              <p class="font-mono text-[10px] break-all text-cream-dim">{draft.revision}</p>
              {#if draft.bundle}
                {@const rootPiece = draft.bundle.pieces[draft.bundle.root]}
                {#if rootPiece}
                  <ol aria-label="Draft steps aligned to narration" class="grid gap-1 pl-5 text-xs">
                    {#each rootPiece.definition.steps as step, index (`id` in step ? step.id : index)}
                      {@const stepId = `id` in step ? step.id : `repeat[${String(index + 1)}]`}
                      {@const narrationIndex = draft.alignment[stepId]}
                      {@const narration =
                        narrationIndex === undefined
                          ? undefined
                          : demonstration.narration.find((line) => line.index === narrationIndex)?.text}
                      <li>
                        <span class="font-mono">{stepId}</span>
                        {#if narration}<p class="text-cream-dim">“{narration}”</p>{/if}
                      </li>
                    {/each}
                  </ol>
                  <WorkflowReviewTree bundle={draft.bundle} />
                {/if}
              {/if}
              <p class="text-xs text-cream-dim">Latest read-only preview</p>
              {#if draft.latest_preview}
                <ul aria-label="Latest preview result" class="grid gap-1 text-xs">
                  {#each draft.latest_preview.steps as result (result.step)}
                    <li class="flex flex-wrap justify-between gap-2 rounded bg-ink p-2">
                      <span class="font-mono">{result.step}</span>
                      <span class={workflowPreviewIsClean(result) ? "text-cream-dim" : "text-copper"}>
                        {workflowPreviewLabel(result)}
                      </span>
                    </li>
                  {/each}
                </ul>
              {:else}
                <p class="text-xs text-cream-dim">No preview yet</p>
              {/if}
            </div>
          {/if}
        </article>
      {/each}
    </section>
  {/if}
  {#if review}
    {@const current = review}
    <section aria-label="Workflow review" class="grid gap-3 rounded border border-line p-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h3 class="font-serif text-xl text-cream">{review.name}</h3>
        <button
          type="button"
          class="min-h-9 px-3 text-sm"
          disabled={busy}
          onclick={() => {
            decide(current);
          }}
        >
          {review.approved ? "Revoke" : "Approve"}
        </button>
      </div>
      <p class="text-sm text-cream-dim">{review.use_when}</p>
      <p class="font-mono text-xs break-all text-cream-dim">Bundle {review.revision}</p>
      <p class="text-xs text-cream-dim">
        Requires cancellable window actions{review.bundle.requires.length
          ? ` and ${review.bundle.requires.join(", ")}`
          : ""}
      </p>
      <WorkflowReviewTree bundle={review.bundle} />
    </section>
  {/if}
</Modal>
