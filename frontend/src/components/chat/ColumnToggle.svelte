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
  const toggleClass = $derived(collapsed ? "text-copper-hot border-[rgb(217_142_74/0.5)]" : "");
</script>

<button
  class="column-toggle flex h-[34px] flex-none items-center justify-center gap-1.5 bg-ink-2 px-[9px] {toggleClass}"
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
      class="chevron size-[13px] fill-none stroke-current stroke-2 transition-transform duration-[220ms] motion-reduce:transition-none [stroke-linecap:round] [stroke-linejoin:round]"
      class:rotate-180={collapsed}
      aria-hidden="true"
      viewBox="0 0 24 24"><path d="m15 5-7 7 7 7" /></svg
    >
    <span>lines</span>
  {:else}
    <span class="led" class:running={count > 0}></span>
    <span>jacks</span>
    <svg
      class="chevron size-[13px] fill-none stroke-current stroke-2 transition-transform duration-[220ms] motion-reduce:transition-none [stroke-linecap:round] [stroke-linejoin:round]"
      class:rotate-180={collapsed}
      aria-hidden="true"
      viewBox="0 0 24 24"><path d="m9 5 7 7-7 7" /></svg
    >
  {/if}
</button>

<style>
  /* Tailwind's `max-*` variants are exclusive of the boundary, so the
     documented `(max-width: 899px)` narrow breakpoint stays hand-written —
     at exactly 899px it must keep agreeing with `NARROW_MAX_WIDTH`. The
     tablet band lives here with it so the breakpoints read as one block. */
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
