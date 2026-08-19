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

  const topic = $derived((room.conversation?.topic ?? "").trim());
  /** Live jacks only: the badge answers "is anything running", not "how many
   *  rows are in the table". */
  const liveJacks = $derived(latestJacks(room.attachments).filter(isLive).length);
</script>

<div id="topbar">
  <button
    class="drawer-toggle lines"
    type="button"
    title="lines"
    aria-label="show lines"
    aria-expanded={layout.drawer === "rail"}
    onclick={() => {
      layout.toggle("rail");
    }}>☰</button
  >

  <span id="convname">{room.conversation?.name ?? "—"}</span>
  {#if room.conversation}
    <button
      id="convmeta"
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
      class="task-toggle"
      type="button"
      title="shared line tasks"
      aria-label="open shared line tasks"
      onclick={() => dialogs.open(TaskDrawer)}
    >
      <svg aria-hidden="true" viewBox="0 0 24 24"
        ><path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" /></svg
      >
      <span>tasks</span>
    </button>
  {/if}

  <AccountMenu />

  <button
    class="drawer-toggle jacks"
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
  #topbar {
    padding: 16px 28px;
    border-bottom: 1px solid var(--color-line);
    display: flex;
    align-items: baseline;
    gap: 14px;
  }
  #convname {
    font-family: var(--font-serif);
    font-size: 24px;
    font-weight: 400;
    font-style: italic;
    color: var(--color-cream);
    flex: none;
  }
  /* A button, not a span: it does something when clicked, so it should be
     reachable by keyboard and announced as an action. Styled back down to look
     like the line of text it is. */
  #convmeta {
    background: none;
    border: 0;
    padding: 0;
    font: inherit;
    text-align: left;
    color: var(--color-cream-dim);
    font-size: 11.5px;
    font-style: italic;
    min-width: 0;
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    cursor: pointer;
    border-bottom: 1px dashed transparent;
    transition: color 0.15s;
  }
  #convmeta:hover {
    color: var(--color-copper-hot);
    background: none;
    border-bottom-color: rgb(217 142 74 / 0.4);
  }
  #convmeta.unset {
    color: var(--color-cream-faint);
  }

  /* Both rails are on screen at all times above the breakpoint, so their
     handles are not merely unnecessary there — they would be a second,
     contradictory way to reach something already visible. */
  .drawer-toggle {
    display: none;
  }
  .task-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    flex: none;
    height: 34px;
    padding: 0 10px;
  }
  .task-toggle svg {
    width: 15px;
    height: 15px;
    fill: none;
    stroke: currentColor;
    stroke-linecap: round;
    stroke-width: 2;
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
