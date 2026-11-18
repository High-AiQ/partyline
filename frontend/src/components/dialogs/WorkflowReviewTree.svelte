<script lang="ts">
  import type { WorkflowReview } from "../../lib/workflow-api";

  import WorkflowReviewSteps from "./WorkflowReviewSteps.svelte";

  interface Props {
    bundle: WorkflowReview["bundle"];
  }

  let { bundle }: Props = $props();

  function jump(name: string): void {
    const piece = document.getElementById(`workflow-piece-${name}`);
    if (!(piece instanceof HTMLDetailsElement)) return;
    piece.open = true;
    piece.scrollIntoView({ block: "nearest" });
    piece.querySelector("summary")?.focus();
  }
</script>

{#each Object.entries(bundle.pieces) as [name, piece] (name)}
  <details open={name === bundle.root} id={`workflow-piece-${name}`} class="rounded border border-line p-2">
    <summary class="text-sm font-semibold">{name}</summary>
    <div class="mt-2 grid gap-2">
      <p class="text-xs text-cream-dim">{piece.definition.description}</p>
      <p class="font-mono text-xs break-all text-cream-dim">{piece.path} · {piece.revision}</p>
      {#if Object.keys(piece.definition.parameters).length}
        <details>
          <summary class="text-xs">Parameters</summary>
          <pre class="text-xs whitespace-pre-wrap [overflow-wrap:anywhere]">{JSON.stringify(
              piece.definition.parameters,
              null,
              2,
            )}</pre>
        </details>
      {/if}
      <WorkflowReviewSteps entries={piece.definition.steps} {jump} />
    </div>
  </details>
{/each}
