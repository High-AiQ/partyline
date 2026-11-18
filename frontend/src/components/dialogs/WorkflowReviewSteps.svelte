<script lang="ts">
  import type { ReviewEntry } from "../../lib/workflow-api";
  import WorkflowReviewSteps from "./WorkflowReviewSteps.svelte";

  interface Props {
    entries: ReviewEntry[];
    jump: (name: string) => void;
  }

  let { entries, jump }: Props = $props();

  function label(value: unknown): string {
    return typeof value === "string" ? value : JSON.stringify(value);
  }

  function actionLabel(entry: ReviewEntry): string {
    return "action" in entry ? label(entry.target.name) : "";
  }
</script>

<ol class="grid gap-1 border-l border-line pl-3">
  {#each entries as entry, index (index)}
    <li class="text-xs">
      {#if "for_each" in entry}
        <p>Repeat for {label(entry.for_each)}</p>
        <WorkflowReviewSteps entries={entry.steps} {jump} />
      {:else if "use" in entry}
        {@const destinations =
          typeof entry.use === "string" ? [["", entry.use]] : Object.entries(entry.use.cases)}
        <details>
          <summary
            >{entry.id} · {typeof entry.use === "string" ? entry.use : `choose by ${entry.use.by}`}</summary
          >
          {#each destinations as [choice, name] (choice)}
            {#if name}
              <p>
                {#if choice}{choice} →{/if}
                <button
                  class="border-0 bg-transparent p-1 text-xs text-copper underline"
                  type="button"
                  onclick={() => {
                    jump(name);
                  }}>{name}</button
                >
              </p>
            {/if}
          {/each}
          {#if Object.keys(entry.with).length || Object.keys(entry.case_bindings).length}
            <details>
              <summary>Parameter bindings</summary>
              <pre class="my-1 whitespace-pre-wrap [overflow-wrap:anywhere] text-cream-dim">{JSON.stringify(
                  { with: entry.with, cases: entry.case_bindings },
                  null,
                  2,
                )}</pre>
            </details>
          {/if}
        </details>
      {:else}
        <details>
          <summary>{entry.id} · {entry.action} · {actionLabel(entry)}</summary>
          <pre class="my-1 whitespace-pre-wrap [overflow-wrap:anywhere] text-cream-dim">{JSON.stringify(
              entry,
              null,
              2,
            )}</pre>
        </details>
        {#if entry.confirm}
          <p class="font-semibold text-copper-hot">Confirmation required · {entry.effect}</p>
        {/if}
      {/if}
    </li>
  {/each}
</ol>
