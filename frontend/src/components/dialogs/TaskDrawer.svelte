<script lang="ts">
  /** The line's shared task board, presented as a right-edge drawer. */
  import { ApiError } from "../../lib/api";
  import { coordinationApi } from "../../lib/coordination-api";
  import type { Task } from "../../lib/contracts";
  import { latestJacks } from "../../lib/attachments";
  import { room } from "../../state/room.svelte.js";
  import { session } from "../../state/session.svelte.js";
  import TaskCard from "./TaskCard.svelte";

  interface Props {
    close: () => void;
  }

  let { close }: Props = $props();

  let tasks = $state<Task[]>([]);
  let body = $state("");
  let owner = $state("");
  let loading = $state(true);
  let saving = $state(false);
  let error = $state("");
  let pressedBackdrop = $state(false);

  const conversationId = $derived(room.conversation?.id ?? null);
  const owners = $derived.by(() => {
    const names = [
      session.handle ?? "",
      ...latestJacks(room.attachments).map((jack) => jack.name),
      ...tasks.map((task) => task.owner ?? ""),
    ];
    return [...new Set(names.filter(Boolean))].sort((left, right) => left.localeCompare(right));
  });
  const openTasks = $derived(tasks.filter((task) => task.status === "open"));
  const doneTasks = $derived(tasks.filter((task) => task.status === "done"));

  function message(error: unknown, fallback: string): string {
    return error instanceof ApiError ? error.message : fallback;
  }

  async function load(id: string | null): Promise<void> {
    if (!id) return;
    loading = true;
    error = "";
    try {
      const found = await coordinationApi.tasks(id);
      if (id !== conversationId) return;
      tasks = found;
    } catch (caught) {
      if (id !== conversationId) return;
      error = message(caught, "could not load tasks");
    } finally {
      if (id === conversationId) loading = false;
    }
  }

  $effect(() => {
    void load(conversationId);
  });

  async function add(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const text = body.trim();
    if (!conversationId || !text || saving) return;
    saving = true;
    error = "";
    try {
      const task = await coordinationApi.createTask(conversationId, {
        body: text,
        owner: owner || null,
      });
      tasks = [...tasks, task];
      body = "";
    } catch (caught) {
      error = message(caught, "could not add task");
    } finally {
      saving = false;
    }
  }

  async function update(
    task: Task,
    patch: { status?: "open" | "done"; owner?: string | null },
  ): Promise<void> {
    if (!conversationId) return;
    error = "";
    try {
      const changed = await coordinationApi.updateTask(task.id, patch);
      tasks = tasks.map((candidate) => (candidate.id === changed.id ? changed : candidate));
    } catch (caught) {
      error = message(caught, "could not update task");
    }
  }

  async function remove(task: Task): Promise<void> {
    if (!conversationId) return;
    error = "";
    try {
      await coordinationApi.deleteTask(task.id);
      tasks = tasks.filter((candidate) => candidate.id !== task.id);
    } catch (caught) {
      error = message(caught, "could not delete task");
    }
  }
</script>

<div
  class="task-overlay"
  role="presentation"
  onmousedown={(event) => (pressedBackdrop = event.target === event.currentTarget)}
  onclick={(event) => {
    if (event.target === event.currentTarget && pressedBackdrop) close();
  }}
>
  <div class="task-drawer" role="dialog" aria-modal="true" aria-label="line tasks">
    <header>
      <div>
        <p>shared state</p>
        <h2>line tasks</h2>
      </div>
      <button class="close" type="button" title="close" aria-label="close tasks" onclick={close}>✕</button>
    </header>

    <form class="task-form" onsubmit={add}>
      <label for="taskBody">new task</label>
      <textarea id="taskBody" bind:value={body} maxlength="500" rows="3" placeholder="What needs doing?"
      ></textarea>
      <div class="assign-row">
        <label for="taskOwner">assign to</label>
        <select id="taskOwner" bind:value={owner}>
          <option value="">unassigned</option>
          {#each owners as name (name)}
            <option value={name}>@{name}</option>
          {/each}
        </select>
        <button class="primary" type="submit" disabled={!body.trim() || saving}>
          {saving ? "adding…" : "add task"}
        </button>
      </div>
    </form>

    {#if error}<p class="task-error" role="alert">{error}</p>{/if}

    <div class="task-list" aria-live="polite">
      {#if loading}
        <p class="empty">loading tasks…</p>
      {:else if !tasks.length}
        <p class="empty">nothing open — this line is clear</p>
      {:else}
        {#each openTasks as task (task.id)}
          <TaskCard {task} {owners} onupdate={update} onremove={remove} />
        {/each}

        {#if doneTasks.length}
          <details>
            <summary>{doneTasks.length} completed</summary>
            {#each doneTasks as task (task.id)}
              <TaskCard {task} {owners} onupdate={update} onremove={remove} />
            {/each}
          </details>
        {/if}
      {/if}
    </div>
  </div>
</div>

<style>
  .task-overlay {
    position: fixed;
    inset: 0;
    z-index: 50;
    background: rgb(8 10 9 / 0.66);
    backdrop-filter: blur(2px);
  }
  .task-drawer {
    position: absolute;
    inset: 0 0 0 auto;
    width: min(430px, 94vw);
    display: flex;
    flex-direction: column;
    background: var(--color-ink-2);
    border-left: 1px solid var(--color-panel-line);
    box-shadow: -24px 0 60px rgb(0 0 0 / 0.5);
    animation: drawer-in 0.22s ease both;
  }
  header {
    min-height: 70px;
    padding: 10px 10px 10px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px dashed var(--color-line);
  }
  header p,
  .task-form label {
    color: var(--color-cream-faint);
    font-size: 9px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }
  h2 {
    color: var(--color-cream);
    font-family: var(--font-serif);
    font-size: 24px;
    font-style: italic;
    font-weight: 400;
    line-height: 1.1;
  }
  .close {
    width: 44px;
    height: 44px;
    padding: 0;
    border: 0;
    background: none;
  }
  .close:hover {
    color: var(--color-red);
    background: none;
  }
  .task-form {
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 7px;
    border-bottom: 1px solid var(--color-line);
  }
  textarea {
    width: 100%;
    resize: vertical;
    min-height: 68px;
    padding: 9px 10px;
    color: var(--color-cream);
    background: var(--color-ink);
    border: 1px solid var(--color-line);
    border-radius: 4px;
    font: inherit;
    outline: 0;
  }
  textarea:focus {
    border-color: var(--color-copper);
  }
  .assign-row {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 8px;
  }
  .task-error {
    margin: 12px 20px 0;
    color: var(--color-red);
    font-size: 11px;
  }
  .task-list {
    min-height: 0;
    overflow-y: auto;
    padding: 10px 14px 20px;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .empty {
    color: var(--color-cream-faint);
    font-size: 11px;
    font-style: italic;
    padding: 20px 4px;
    text-align: center;
  }
  details {
    margin-top: 8px;
  }
  summary {
    cursor: pointer;
    color: var(--color-cream-faint);
    font-size: 10px;
    margin-bottom: 7px;
  }
  @keyframes drawer-in {
    from {
      opacity: 0;
      transform: translateX(18px);
    }
  }
  @media (max-width: 480px) {
    .task-drawer {
      width: 100vw;
    }
    .assign-row {
      grid-template-columns: 1fr auto;
    }
    .assign-row label {
      grid-column: 1 / -1;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .task-drawer {
      animation: none;
    }
  }
</style>
