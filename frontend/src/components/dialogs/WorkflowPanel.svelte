<script lang="ts">
  import Modal from "../Modal.svelte";
  import WorkflowReviewTree from "./WorkflowReviewTree.svelte";
  import { workflowApi, type WorkflowListing, type WorkflowReview } from "../../lib/workflow-api";

  interface Props {
    line: string;
    close: () => void;
  }

  let { line, close }: Props = $props();
  let workflows = $state<WorkflowListing[]>([]);
  let review = $state<WorkflowReview>();
  let busy = $state(true);
  let error = $state("");

  async function load(): Promise<void> {
    workflows = (await workflowApi.list(line)).workflows;
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
