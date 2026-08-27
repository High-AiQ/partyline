<script lang="ts">
  /** A desktop side-column control that remains in the line when its panel leaves. */
  import { layout } from "../../state/layout.svelte.js";
  import type { DrawerName } from "../../state/layout.svelte.js";

  interface Props {
    side: DrawerName;
    count?: number;
  }

  let { side, count = 0 }: Props = $props();
  const collapsed = $derived(side === "rail" ? layout.railCollapsed : layout.boardCollapsed);
  const noun = $derived(side === "rail" ? "lines" : "processes on this line");
</script>

<button
  class="column-toggle flex h-[34px] flex-none items-center justify-center gap-1.5 bg-ink-2 px-[9px]"
  class:collapsed
  type="button"
  title={collapsed ? `show ${noun}` : `hide ${noun}`}
  aria-label={collapsed ? `show ${noun}` : `hide ${noun}`}
  aria-controls={side}
  aria-expanded={!collapsed}
  onclick={() => {
    layout.toggleColumn(side);
  }}
>
  {#if side === "rail"}
    <svg
      class="size-[13px] fill-none stroke-current stroke-2 transition-transform duration-[220ms] motion-reduce:transition-none [stroke-linecap:round] [stroke-linejoin:round]"
      aria-hidden="true"
      viewBox="0 0 24 24"><path d="m15 5-7 7 7 7" /></svg
    >
    <span>lines</span>
  {:else}
    <span class="led" class:running={count > 0}></span>
    <span>jacks</span>
    <svg
      class="size-[13px] fill-none stroke-current stroke-2 transition-transform duration-[220ms] motion-reduce:transition-none [stroke-linecap:round] [stroke-linejoin:round]"
      aria-hidden="true"
      viewBox="0 0 24 24"><path d="m9 5 7 7-7 7" /></svg
    >
  {/if}
</button>

<style>
  /* The collapsed tint and the rotated chevron are a class-based state with a
     descendant selector — a poor fit for utility variants. The breakpoints
     stay hand-written: Tailwind's `max-*` variants are exclusive of the
     boundary, and `(max-width: 899px)` must keep agreeing with
     `NARROW_MAX_WIDTH`. */
  .column-toggle.collapsed {
    color: var(--color-copper-hot);
    border-color: rgb(217 142 74 / 0.5);
  }
  .column-toggle.collapsed svg {
    transform: rotate(180deg);
  }
  @media (min-width: 900px) and (max-width: 1199px) {
    button {
      min-width: 34px;
      padding: 0 7px;
    }
    button > span:not(.led) {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
    }
  }
  @media (max-width: 899px) {
    button {
      display: none;
    }
  }
</style>
