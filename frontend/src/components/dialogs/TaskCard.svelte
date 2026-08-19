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

<div class="task-row" class:done>
  <button
    class="check"
    type="button"
    title={done ? "reopen" : "mark done"}
    aria-label="{done ? 'reopen' : 'mark done'} task: {view.summary}"
    onclick={() => onupdate(task, { status: done ? "open" : "done" })}
  >
    {#if done}✓{:else}<span></span>{/if}
  </button>
  <div class="task-main">
    <p>{view.summary}</p>
    {#if view.doneWhen && !done}
      <p class="done-when" title={view.doneWhen}>⤷ {view.doneWhen}</p>
    {/if}
    {#if !done}
      <label>
        <span>owner</span>
        <select
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
    class="remove"
    type="button"
    title="delete task"
    aria-label="delete task: {view.summary}"
    onclick={() => onremove(task)}>✕</button
  >
</div>

<style>
  .task-row {
    display: flex;
    align-items: flex-start;
    gap: 9px;
    padding: 6px 8px;
    border: 1px solid var(--color-line);
    border-radius: 5px;
    background: var(--color-ink-3);
  }
  .task-main {
    flex: 1;
    min-width: 0;
  }
  p {
    color: var(--color-cream);
    overflow-wrap: anywhere;
    font-size: 12px;
  }
  .done-when {
    color: var(--color-cream-faint);
    font-size: 10.5px;
    margin-top: 2px;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    overflow: hidden;
  }
  label {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-top: 5px;
  }
  label span {
    color: var(--color-cream-faint);
    font-size: 9px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }
  select {
    padding: 3px 6px;
    font-size: 10px;
  }
  .check {
    width: 26px;
    height: 26px;
    flex: none;
    padding: 0;
    display: grid;
    place-items: center;
    color: var(--color-green);
  }
  .check span {
    width: 11px;
    height: 11px;
    border: 1px solid currentColor;
    border-radius: 2px;
  }
  .remove {
    width: 26px;
    height: 26px;
    padding: 0;
    flex: none;
    border: 0;
    background: none;
  }
  .remove:hover {
    color: var(--color-red);
    background: none;
  }
  .done {
    opacity: 0.62;
    margin-top: 6px;
    padding: 4px 8px;
  }
  .done p {
    text-decoration: line-through;
  }
</style>
