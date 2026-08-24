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
  class="column-toggle"
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
    <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m15 5-7 7 7 7" /></svg>
    <span>lines</span>
  {:else}
    <span class="led" class:running={count > 0}></span>
    <span>jacks</span>
    <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m9 5 7 7-7 7" /></svg>
  {/if}
</button>

<style>
  button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    flex: none;
    height: 34px;
    padding: 0 9px;
    background: var(--color-ink-2);
  }
  svg {
    width: 13px;
    height: 13px;
    fill: none;
    stroke: currentColor;
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-width: 2;
    transition: transform 0.22s ease;
  }
  button.collapsed {
    color: var(--color-copper-hot);
    border-color: rgb(217 142 74 / 0.5);
  }
  button.collapsed svg {
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

  @media (prefers-reduced-motion: reduce) {
    svg {
      transition: none;
    }
  }
</style>
