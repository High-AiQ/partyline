<script lang="ts">
  /**
   * One row of the rail: the line, its star, its subtree toggle and its ⋯.
   *
   * The star is a sibling of the row button, not a child: a button cannot hold a
   * button, and a click on the star must not open the line. It floats over an
   * empty slot reserved inside the row button, so the name's alignment never
   * depends on the star state. Its hit area is padded beyond the 13px glyph
   * without widening the row.
   */
  import { screenStatus } from "../../state/screen-status.svelte";
  import ShareIcon from "./ShareIcon.svelte";
  import TaskStatusChip from "./TaskStatusChip.svelte";
  import TaskModeIcon from "./TaskModeIcon.svelte";
  import ChapterMark from "./ChapterMark.svelte";
  import type { TreeRow } from "../../lib/line-tree";
  import { tooltip } from "../../lib/tooltip";
  import { chapterMarker } from "../../lib/chapters";
  import type { Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte";
  import { toggleConversationStar } from "../../state/conversation-star";

  interface Props {
    row: TreeRow<Conversation>;
    /** Bulk select mode: the row toggles a checkbox instead of opening the line. */
    selecting: boolean;
    checked: boolean;
    /** This row's ⋯ menu is open, which keeps its actions lit. */
    menuOpen: boolean;
    onpick: () => void;
    ontree: () => void;
    onmenu: (event: MouseEvent) => void;
  }

  let { row, selecting, checked, menuOpen, onpick, ontree, onmenu }: Props = $props();

  const conversation = $derived(row.line);
  const depth = $derived(row.depth);
  const indicators = $derived(screenStatus.indicators.filter((item) => item.conv_id === conversation.id));
  const chain = $derived(chapterMarker(conversation, room.conversations));
  const active = $derived(room.conversation?.id === conversation.id);
  const starred = $derived(conversation.starred ?? false);
  /** Where the star slot starts: the row padding plus the fixed-width things before it. */
  const slotLeft = $derived(20 + Math.min(depth, 4) * 16 + (selecting ? 21 : 0) + (depth > 0 ? 18 : 0) + 15);
</script>

<div class="conv-row group relative flex items-stretch" class:menu-open={menuOpen}>
  <button
    class="conv relative flex min-w-0 w-full flex-1 cursor-pointer items-center gap-2 border-0 p-[9px] pl-5 text-left text-[13.5px] [font-family:inherit] {active
      ? 'bg-ink-3 text-copper-hot'
      : 'bg-transparent text-cream-dim group-hover:bg-ink-3 group-hover:text-cream group-focus-within:bg-ink-3 group-focus-within:text-cream group-[.menu-open]:bg-ink-3 group-[.menu-open]:text-cream'}"
    class:active
    style:padding-right="{row.descendants > 0 ? 120 : 54}px"
    style:padding-left="{20 + Math.min(depth, 4) * 16}px"
    aria-pressed={selecting ? checked : undefined}
    onclick={onpick}
  >
    {#if selecting}<input
        class="bulk-check pointer-events-none m-0 size-[13px] flex-none"
        type="checkbox"
        tabindex="-1"
        aria-hidden="true"
        {checked}
      />{/if}
    {#if depth > 0}<span class="w-[10px] flex-none text-cream-faint" aria-label="child line">↳</span>{/if}
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
    <span class="star-slot w-3 flex-none" aria-hidden="true"></span>
    <span class="min-w-0 flex flex-col items-start gap-1">
      <span class="conv-name flex w-full min-w-0 items-center gap-1"
        ><TaskModeIcon line={conversation} /><ShareIcon {indicators} /><span
          class="min-w-0 flex-1 truncate"
          use:tooltip={{ label: conversation.name }}>{conversation.name}</span
        >{#if chain.label ?? chain.continuedIn}<ChapterMark {chain} />{/if}</span
      >
      <TaskStatusChip status={conversation.task_status} round={conversation.task_round} />
    </span>
  </button>
  <button
    type="button"
    class="conv-star absolute top-0 flex h-[38px] w-8 items-center justify-center rounded-sm border-0 bg-transparent p-0 hover:bg-transparent hover:text-gold focus-visible:outline-2 focus-visible:outline-copper-hot {starred
      ? 'text-gold'
      : 'text-cream-faint'}"
    style:left="{slotLeft - 10}px"
    use:tooltip={{ label: starred ? "unstar line" : "star line" }}
    aria-label="{starred ? 'Unstar' : 'Star'} {conversation.name}"
    aria-pressed={starred}
    onclick={(event) => {
      event.stopPropagation();
      void toggleConversationStar(room, conversation.id);
    }}
  >
    <svg
      class="star-glyph"
      viewBox="0 0 16 16"
      width="13"
      height="13"
      fill={starred ? "currentColor" : "none"}
      stroke="currentColor"
      stroke-width="1.4"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d="M8 1.6 10 6l4.6.5-3.4 3.1 1 4.6L8 11.8l-4.2 2.4 1-4.6L1.4 6.5 6 6z" />
    </svg>
  </button>
  {#if row.descendants > 0}
    <button
      type="button"
      class="tree-toggle absolute top-1/2 right-11 -translate-y-1/2 bg-ink-2 px-1 text-xs text-cream-faint hover:text-cream"
      aria-label={row.forced
        ? `Sublines of ${conversation.name} expanded to keep a nested line visible`
        : `${row.expanded ? "Collapse" : "Expand"} sublines of ${conversation.name}`}
      disabled={row.forced}
      aria-expanded={row.expanded}
      onclick={ontree}>{row.expanded ? "▾" : "▸"}</button
    >
    {#if !row.expanded}
      <span
        class="tree-count absolute top-1/2 right-[76px] -translate-y-1/2 bg-ink-2 px-1 text-[10px] text-cream-faint"
        use:tooltip={{
          label: `${String(row.descendants)} sublines, ${String(row.liveDescendants)} active processes`,
        }}
        aria-label="{row.descendants} sublines, {row.liveDescendants} active processes"
        >{row.descendants} · {row.liveDescendants}▶</span
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
        aria-expanded={menuOpen}
        onclick={onmenu}>⋯</button
      >
    </div>
  {/if}
</div>

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
