<script lang="ts">
  /** One task, with the same controls in its open and completed states. */
  import type { Task } from "../../lib/contracts";
  import { taskView } from "../../lib/task-view";

  interface Props {
    task: Task;
    owners: readonly string[];
    onupdate: (task: Task, patch: { status?: "open" | "done"; owner?: string | null }) => Promise<void>;
    onremove: (task: Task) => Promise<void>;
  }

  let { task, owners, onupdate, onremove }: Props = $props();
  const done = $derived(task.status === "done");
  const view = $derived(taskView(task));
</script>

<div
  class="task-row flex items-start gap-[9px] rounded-[5px] border border-line bg-ink-3 px-[8px] {done
    ? 'mt-[6px] py-[4px] opacity-[0.62]'
    : 'py-[6px]'}"
>
  <button
    class="grid h-[26px] w-[26px] flex-none place-items-center p-0 text-green"
    type="button"
    title={done ? "reopen" : "mark done"}
    aria-label="{done ? 'reopen' : 'mark done'} task: {view.summary}"
    onclick={() => onupdate(task, { status: done ? "open" : "done" })}
  >
    {#if done}✓{:else}<span class="h-[11px] w-[11px] rounded-[2px] border border-current"></span>{/if}
  </button>
  <div class="task-main min-w-0 flex-1">
    <p class="text-[12px] wrap-anywhere text-cream {done ? 'line-through' : ''}">{view.summary}</p>
    {#if view.doneWhen && !done}
      <p
        class="done-when mt-[2px] text-[10.5px] wrap-anywhere line-clamp-2 text-cream-faint"
        title={view.doneWhen}
      >
        ⤷ {view.doneWhen}
      </p>
    {/if}
    {#if !done}
      <label class="mt-[5px] flex items-center gap-[7px]">
        <span class="text-[9px] uppercase tracking-[0.12em] text-cream-faint">owner</span>
        <select
          class="px-[6px] py-[3px] text-[10px]"
          value={task.owner ?? ""}
          aria-label="owner for {view.summary}"
          onchange={(event) => onupdate(task, { owner: event.currentTarget.value || null })}
        >
          <option value="">unassigned</option>
          {#each owners as name (name)}
            <option value={name}>@{name}</option>
          {/each}
        </select>
      </label>
    {/if}
  </div>
  <button
    class="h-[26px] w-[26px] flex-none border-0 bg-transparent p-0 hover:bg-transparent hover:text-red"
    type="button"
    title="delete task"
    aria-label="delete task: {view.summary}"
    onclick={() => onremove(task)}>✕</button
  >
</div>
