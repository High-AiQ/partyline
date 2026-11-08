<script lang="ts">
  /**
   * The lines you can be on.
   *
   * The row's actions are hidden until hover, and the menu is a single instance
   * anchored to whichever ⋯ opened it. While a menu is open its row keeps its
   * actions lit, so the ⋯ does not vanish out from under the pointer on the way
   * down to the menu.
   */
  import { SvelteSet } from "svelte/reactivity";
  import TaskStatusChip from "./TaskStatusChip.svelte";
  import TaskModeIcon from "./TaskModeIcon.svelte";
  import LineMenu from "./LineMenu.svelte";
  import { lineTree, readExpandedLines, storeExpandedLines } from "../../lib/line-tree";
  import { toggleSelection } from "../../lib/bulk-select";
  import { tooltip } from "../../lib/tooltip";
  import type { Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte";

  interface Props {
    onrename: (conversation: Conversation) => void;
    onmanagement: (conversation: Conversation) => void;
    oncloseprocesses: (conversation: Conversation) => void;
    ondelete: (conversation: Conversation) => void;
    onarchivemany?: (conversations: Conversation[], done: () => void) => void;
  }

  interface MenuState {
    anchor: HTMLButtonElement;
    conversation: Conversation;
  }

  let { onrename, onmanagement, oncloseprocesses, ondelete, onarchivemany }: Props = $props();

  let expanded = $state<Set<string>>(readExpandedLines());
  const rows = $derived(lineTree(room.conversations, expanded, room.conversation?.id));

  function toggleTree(id: string): void {
    const next = new SvelteSet(expanded);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    expanded = next;
    storeExpandedLines(next);
  }

  /** Bulk select mode: rows toggle a checkbox instead of opening the line. */
  let selecting = $state(false);
  let selected = $state<Set<string>>(new Set());
  const chosen = $derived(room.conversations.filter((line) => selected.has(line.id)));

  function stopSelecting(): void {
    selecting = false;
    selected = new Set();
  }

  /** `{anchor, conversation}` while a menu is open, else null. */
  let menu = $state<MenuState | null>(null);

  function toggle(event: MouseEvent, conversation: Conversation): void {
    event.stopPropagation();
    if (!(event.currentTarget instanceof HTMLButtonElement)) return;
    const anchor = event.currentTarget;
    menu = menu?.anchor === anchor ? null : { anchor, conversation };
  }
</script>

<!-- Any click that is not on a ⋯ dismisses the menu. The buttons stop their own
     propagation, so this cannot fight with the toggle above. -->
<svelte:body on:click={() => (menu = null)} />

{#if onarchivemany && room.conversations.length}
  <div class="bulk-bar flex items-center justify-end gap-1.5 px-5 pt-2 text-[11px] text-cream-faint">
    {#if selecting}
      <span class="mr-auto">{chosen.length} selected</span>
      <button
        type="button"
        class="bulk-archive px-2 py-0.5 text-[11px]"
        disabled={chosen.length === 0}
        onclick={() => {
          onarchivemany(chosen, stopSelecting);
        }}>archive {chosen.length || ""}</button
      >
      <button type="button" class="bulk-cancel px-2 py-0.5 text-[11px]" onclick={stopSelecting}>cancel</button
      >
    {:else}
      <button
        type="button"
        class="bulk-select px-2 py-0.5 text-[11px]"
        use:tooltip={{ label: "select several lines to archive at once" }}
        onclick={() => (selecting = true)}>select</button
      >
    {/if}
  </div>
{/if}

<nav id="convs" class="min-h-0 flex-1 overflow-y-auto py-2.5" aria-label="lines">
  {#each rows.filter((row) => row.visible) as { line: conversation, depth, descendants, liveDescendants, expanded: isExpanded, forced } (conversation.id)}
    {@const open = menu?.conversation.id === conversation.id}
    <div class="conv-row group relative flex items-stretch" class:menu-open={open}>
      <button
        class="conv relative flex min-w-0 w-full flex-1 cursor-pointer items-center gap-2 border-0 p-[9px] pl-5 text-left text-[13.5px] [font-family:inherit] {room
          .conversation?.id === conversation.id
          ? 'bg-ink-3 text-copper-hot'
          : 'bg-transparent text-cream-dim group-hover:bg-ink-3 group-hover:text-cream group-focus-within:bg-ink-3 group-focus-within:text-cream group-[.menu-open]:bg-ink-3 group-[.menu-open]:text-cream'}"
        class:active={room.conversation?.id === conversation.id}
        style:padding-right="{descendants > 0 ? 120 : 54}px"
        style:padding-left="{20 + Math.min(depth, 4) * 16}px"
        use:tooltip={{ label: conversation.name }}
        aria-pressed={selecting ? selected.has(conversation.id) : undefined}
        onclick={() => {
          if (selecting) selected = toggleSelection(selected, conversation.id, room.conversations);
          else void room.open(conversation);
        }}
      >
        {#if selecting}<input
            class="bulk-check pointer-events-none"
            type="checkbox"
            tabindex="-1"
            aria-hidden="true"
            checked={selected.has(conversation.id)}
          />{/if}
        {#if depth > 0}<span class="text-cream-faint" aria-label="child line">↳</span>{/if}
        <span class="inline-flex w-[7px] flex-none items-center">
          {#if conversation.live_count > 0}
            <span
              class="line-live inline-flex flex-none"
              use:tooltip={{ label: `${String(conversation.live_count)} live` }}
              aria-label="{conversation.live_count} live"
              ><span class="led running" aria-hidden="true"></span></span
            >
          {/if}
        </span>
        <span class="min-w-0 flex flex-col items-start gap-1">
          <span class="conv-name flex w-full min-w-0 items-center gap-1"
            ><TaskModeIcon line={conversation} /><span class="min-w-0 flex-1 truncate"
              >{conversation.name}</span
            ></span
          >
          <TaskStatusChip status={conversation.task_status} round={conversation.task_round} />
        </span>
      </button>
      {#if descendants > 0}
        <button
          type="button"
          class="tree-toggle absolute top-1/2 right-11 -translate-y-1/2 bg-ink-2 px-1 text-xs text-cream-faint hover:text-cream"
          aria-label={forced
            ? `Sublines of ${conversation.name} expanded to show the selected line`
            : `${isExpanded ? "Collapse" : "Expand"} sublines of ${conversation.name}`}
          disabled={forced}
          aria-expanded={isExpanded}
          onclick={() => {
            toggleTree(conversation.id);
          }}>{isExpanded ? "▾" : "▸"}</button
        >
        {#if !isExpanded}
          <span
            class="tree-count absolute top-1/2 right-[76px] -translate-y-1/2 bg-ink-2 px-1 text-[10px] text-cream-faint"
            use:tooltip={{
              label: `${String(descendants)} sublines, ${String(liveDescendants)} active processes`,
            }}
            aria-label="{descendants} sublines, {liveDescendants} active processes"
            >{descendants} · {liveDescendants}▶</span
          >
        {/if}
      {/if}
      {#if !selecting}
        <div
          class="conv-actions absolute top-1/2 right-2 flex -translate-y-1/2 items-center gap-1 opacity-0 transition-opacity pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto group-[.menu-open]:opacity-100 group-[.menu-open]:pointer-events-auto"
        >
          <button
            class="conv-more size-8 bg-ink-2 p-0 text-[15px] leading-none text-cream-faint hover:bg-copper hover:text-ink aria-expanded:bg-copper aria-expanded:text-ink"
            type="button"
            use:tooltip={{ label: "line actions" }}
            aria-label="line actions for {conversation.name}"
            aria-expanded={open}
            onclick={(event) => {
              toggle(event, conversation);
            }}>⋯</button
          >
        </div>
      {/if}
    </div>
  {/each}
</nav>

{#if menu}
  <LineMenu
    anchor={menu.anchor}
    conversation={menu.conversation}
    close={() => (menu = null)}
    {onrename}
    {onmanagement}
    {oncloseprocesses}
    {ondelete}
  />
{/if}

<style>
  /* The active-line copper marker is a pseudo-element on a state class. */
  .conv.active::before {
    content: "";
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--color-copper);
  }

  /* A touch screen has no hover to reveal the row actions with, and Tailwind
     has no `(hover: none)` media-query variant. */
  @media (hover: none) {
    .conv-actions {
      opacity: 1;
      pointer-events: auto;
    }
  }
</style>
