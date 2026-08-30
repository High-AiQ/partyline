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
  class="fixed inset-0 z-50 bg-[rgb(8_10_9/0.66)] backdrop-blur-[2px]"
  role="presentation"
  onmousedown={(event) => (pressedBackdrop = event.target === event.currentTarget)}
  onclick={(event) => {
    if (event.target === event.currentTarget && pressedBackdrop) close();
  }}
>
  <div
    class="task-drawer absolute inset-y-0 right-0 flex w-[min(430px,94vw)] flex-col border-l border-panel-line bg-ink-2 shadow-[-24px_0_60px_rgb(0_0_0/0.5)] max-[480px]:w-screen"
    role="dialog"
    aria-modal="true"
    aria-label="line tasks"
  >
    <header
      class="flex min-h-[70px] items-center justify-between border-b border-dashed border-line p-[10px_10px_10px_20px]"
    >
      <div>
        <p class="text-[9px] uppercase tracking-[0.12em] text-cream-faint">shared state</p>
        <h2 class="font-serif text-[24px] leading-[1.1] font-normal italic text-cream">line tasks</h2>
      </div>
      <button
        class="h-[44px] w-[44px] border-0 bg-transparent p-0 hover:bg-transparent hover:text-red"
        type="button"
        title="close"
        aria-label="close tasks"
        onclick={close}>✕</button
      >
    </header>

    <form class="flex flex-col gap-[7px] border-b border-line px-[20px] py-[18px]" onsubmit={add}>
      <label class="text-[9px] uppercase tracking-[0.12em] text-cream-faint" for="taskBody">new task</label>
      <textarea
        class="min-h-[68px] w-full resize-y rounded-[4px] border border-line bg-ink p-[9px_10px] text-cream [font:inherit] [outline:0] focus:border-copper"
        id="taskBody"
        bind:value={body}
        maxlength="500"
        rows="3"
        placeholder="What needs doing?"></textarea>
      <div
        class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-[8px] max-[480px]:grid-cols-[1fr_auto]"
      >
        <label
          class="text-[9px] uppercase tracking-[0.12em] text-cream-faint max-[480px]:[grid-column:1/-1]"
          for="taskOwner">assign to</label
        >
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

    {#if error}<p class="mx-[20px] mt-[12px] text-[11px] text-red" role="alert">{error}</p>{/if}

    <div class="flex min-h-0 flex-col gap-[5px] overflow-y-auto p-[10px_14px_20px]" aria-live="polite">
      {#if loading}
        <p class="p-[20px_4px] text-center text-[11px] italic text-cream-faint">loading tasks…</p>
      {:else if !tasks.length}
        <p class="p-[20px_4px] text-center text-[11px] italic text-cream-faint">
          nothing open — this line is clear
        </p>
      {:else}
        {#each openTasks as task (task.id)}
          <TaskCard {task} {owners} onupdate={update} onremove={remove} />
        {/each}

        {#if doneTasks.length}
          <details class="mt-[8px]">
            <summary class="mb-[7px] cursor-pointer text-[10px] text-cream-faint"
              >{doneTasks.length} completed</summary
            >
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
  /* Animation stays scoped: keyframes plus the reduced-motion opt-out are the
     kind of CSS Tailwind utilities shouldn't own (docs/frontend.md). Everything
     else on .task-drawer lives in utilities on the markup. */
  .task-drawer {
    animation: drawer-in 0.22s ease both;
  }
  @keyframes drawer-in {
    from {
      opacity: 0;
      transform: translateX(18px);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .task-drawer {
      animation: none;
    }
  }
</style>
