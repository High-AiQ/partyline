<script lang="ts">
  /**
   * The line's name, its topic — which is also the way in to editing it — and,
   * on a narrow screen, the only way to reach the two rails.
   *
   * The drawer controls live here rather than in a second bar of their own:
   * vertical space is the scarcest thing on a phone, and a dedicated toolbar
   * would cost a row of it to repeat what this row already says.
   */
  import { room } from "../../state/room.svelte.js";
  import { dialogs } from "../../state/dialogs.svelte.js";
  import { layout } from "../../state/layout.svelte.js";
  import { isLive, latestJacks } from "../../lib/attachments";
  import TopicDialog from "../dialogs/TopicDialog.svelte";
  import TaskDrawer from "../dialogs/TaskDrawer.svelte";
  import AccountMenu from "./AccountMenu.svelte";
  import ColumnToggle from "./ColumnToggle.svelte";

  const topic = $derived((room.conversation?.topic ?? "").trim());
  /** Live jacks only: the badge answers "is anything running", not "how many
   *  rows are in the table". */
  const liveJacks = $derived(latestJacks(room.attachments).filter(isLive).length);
</script>

<div id="topbar" class="flex items-baseline gap-[14px] border-b border-line px-7 py-4">
  <ColumnToggle side="rail" />

  <button
    class="drawer-toggle lines hidden"
    type="button"
    title="lines"
    aria-label="show lines"
    aria-expanded={layout.drawer === "rail"}
    onclick={() => {
      layout.toggle("rail");
    }}>☰</button
  >

  <span id="convname" class="flex-none font-serif text-[24px] font-normal text-cream italic"
    >{room.conversation?.name ?? "—"}</span
  >
  {#if room.conversation}
    <!-- A button, not a span: it does something when clicked, so it should be
           reachable by keyboard and announced as an action. Styled back down to
           look like the line of text it is. -->
    <button
      id="convmeta"
      class="min-w-0 flex-1 cursor-pointer truncate border-0 border-b border-dashed border-transparent bg-transparent p-0 text-left text-[11.5px] italic transition-colors hover:border-b-copper/40 hover:bg-transparent {topic
        ? 'text-cream-dim hover:text-copper-hot'
        : 'text-cream-faint'}"
      class:unset={!topic}
      type="button"
      title={topic
        ? `${topic}\n\n(click to edit)`
        : "give this line a topic — agents get it in their briefing"}
      onclick={() => dialogs.open(TopicDialog)}>{topic || "set a topic…"}</button
    >
  {/if}

  {#if room.conversation}
    <button
      class="task-toggle inline-flex h-[34px] flex-none items-center gap-1.5 px-2.5"
      type="button"
      title="shared line tasks"
      aria-label="open shared line tasks"
      onclick={() => dialogs.open(TaskDrawer)}
    >
      <svg
        class="size-[15px] fill-none stroke-current stroke-2 [stroke-linecap:round]"
        aria-hidden="true"
        viewBox="0 0 24 24"><path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" /></svg
      >
      <span>tasks</span>
    </button>
  {/if}

  <AccountMenu />
  <ColumnToggle side="board" count={liveJacks} />

  <button
    class="drawer-toggle jacks hidden"
    type="button"
    title="processes on this line"
    aria-label="show processes on this line"
    aria-expanded={layout.drawer === "board"}
    onclick={() => {
      layout.toggle("board");
    }}
  >
    <span class="led" class:running={liveJacks > 0}></span>
    {liveJacks}
  </button>
</div>

<style>
  /* Tailwind's `max-*` variants are exclusive of the boundary, so the
       documented `(max-width: 899px)` narrow breakpoint stays hand-written —
       at exactly 899px it must keep agreeing with `NARROW_MAX_WIDTH`. The
       tablet band lives here with it so the breakpoints read as one block. */
  @media (min-width: 900px) and (max-width: 1199px) {
    #topbar {
      padding: 12px;
      align-items: center;
      gap: 8px;
    }
    #convname {
      min-width: 0;
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    #convmeta {
      display: none;
    }
    .task-toggle span {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
    }
    .task-toggle {
      width: 34px;
      padding: 0;
      justify-content: center;
    }
  }

  @media (max-width: 899px) {
    #topbar {
      padding: 10px 12px;
      align-items: center;
      gap: 10px;
    }
    #convname {
      font-size: 19px;
      min-width: 0;
      flex: 1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    /* The topic is a whole line of prose competing for a width that no longer
         exists. It stays editable from the line's own row in the drawer; it does
         not get to push the controls off screen. */
    #convmeta {
      display: none;
    }
    .drawer-toggle {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 5px;
      flex: none;
      /* 44px is the smallest target a finger hits reliably. */
      min-width: 44px;
      height: 44px;
      padding: 0 10px;
      font-size: 15px;
      background: var(--color-ink-2);
    }
    .drawer-toggle[aria-expanded="true"] {
      color: var(--color-ink);
      background: var(--color-copper);
      border-color: var(--color-copper);
    }
    .jacks {
      font-size: 12px;
    }
    .task-toggle {
      width: 44px;
      height: 44px;
      padding: 0;
      justify-content: center;
    }
    .task-toggle span {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
    }
    .jacks .led {
      width: 6px;
      height: 6px;
    }
  }
</style>
