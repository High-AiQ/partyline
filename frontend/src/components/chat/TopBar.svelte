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
  import AccountMenu from "./AccountMenu.svelte";
  import ColumnToggle from "./ColumnToggle.svelte";
  import ThemeToggle from "./ThemeToggle.svelte";
  import ResourceIndicator from "./ResourceIndicator.svelte";
  import { tooltip } from "../../lib/tooltip";

  const topic = $derived((room.conversation?.topic ?? "").trim());
  /** Live jacks only: the badge answers "is anything running", not "how many
   *  rows are in the table". */
  const liveJacks = $derived(latestJacks(room.attachments).filter(isLive).length);
</script>

<div id="topbar" class="flex items-baseline gap-[14px] border-b border-line px-7 py-4">
  <ColumnToggle side="rail" />

  <button
    class="drawer-toggle lines topbar-action hidden"
    type="button"
    use:tooltip={{ label: "lines" }}
    aria-label="show lines"
    aria-expanded={layout.drawer === "rail"}
    onclick={() => {
      layout.toggle("rail");
    }}>☰</button
  >

  <span
    id="convname"
    class="min-w-0 max-w-[40%] flex-[0_1_auto] truncate font-serif text-[24px] font-normal text-cream italic"
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
      use:tooltip={{
        label: topic
          ? `${topic}\n\n(click to edit)`
          : "give this line a topic — agents get it in their briefing",
        placement: "below",
        followCursor: true,
      }}
      onclick={() => dialogs.open(TopicDialog)}>{topic || "set a topic…"}</button
    >
  {/if}

  <ThemeToggle />
  <ResourceIndicator />
  <AccountMenu />
  <ColumnToggle side="board" count={liveJacks} />

  <button
    class="drawer-toggle jacks topbar-action hidden"
    type="button"
    use:tooltip={{ label: "processes on this line" }}
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
  @media (min-width: 1201px) {
    #topbar {
      gap: 8px;
      padding-left: 16px;
      padding-right: 16px;
    }
  }

  /* Tailwind's `max-*` variants are exclusive of the boundary, so the
       documented `(max-width: 899px)` narrow breakpoint stays hand-written —
       at exactly 899px it must keep agreeing with `NARROW_MAX_WIDTH`. The
       tablet band lives here with it so the breakpoints read as one block. */
  @media (min-width: 900px) and (max-width: 1200px) {
    #topbar {
      padding: 12px;
      align-items: center;
      gap: 4px;
    }
  }

  @media (min-width: 961px) and (max-width: 1200px) {
    #convname {
      max-width: 30%;
    }
  }

  @media (min-width: 1201px) and (max-width: 1440px) {
    #convname {
      max-width: 23%;
    }
  }

  @media (max-width: 899px) {
    #topbar {
      padding: 10px 12px;
      align-items: center;
      gap: 4px;
    }
    #convname {
      font-size: 19px;
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
    }
    .drawer-toggle[aria-expanded="true"] {
      color: var(--color-ink);
      background: var(--color-copper);
      border-color: var(--color-copper);
    }
    .jacks {
      font-size: 12px;
    }
    .jacks .led {
      width: 6px;
      height: 6px;
    }
  }

  @media (max-width: 450px), (min-width: 900px) and (max-width: 960px) {
    #topbar {
      flex-wrap: wrap;
      row-gap: 2px;
    }
    #convname,
    #convmeta {
      order: 2;
      flex: 1 1 calc(50% - 2px);
      max-width: none;
    }
    #convname {
      font-size: 19px;
    }
  }

  @media (min-width: 900px) and (max-width: 960px) {
    #convname {
      font-size: 24px;
    }
  }
</style>
