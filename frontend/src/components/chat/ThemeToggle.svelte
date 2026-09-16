<script lang="ts">
  /** Switches between light and dark; system preference drives it until this is used once. */
  import { theme } from "../../state/theme.svelte.js";
  import { tooltip } from "../../lib/tooltip";

  const isLight = $derived(theme.current === "light");
  /** The accessible name names the setting itself and stays fixed; `aria-pressed`
   *  carries the state, so a screen reader announces one coherent toggle rather
   *  than a label that flips out from under an already-focused control. */
  const tooltipLabel = $derived(`switch to ${isLight ? "dark" : "light"} theme`);
</script>

<button
  class="theme-toggle topbar-action flex h-[34px] flex-none items-center justify-center px-[9px]"
  type="button"
  use:tooltip={{ label: tooltipLabel }}
  aria-label="dark theme"
  aria-pressed={!isLight}
  onclick={() => {
    theme.toggle();
  }}
>
  {#if isLight}
    <svg
      class="size-[15px] fill-none stroke-current stroke-2 [stroke-linecap:round] [stroke-linejoin:round]"
      aria-hidden="true"
      viewBox="0 0 24 24"
      ><circle cx="12" cy="12" r="4" /><path
        d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
      /></svg
    >
  {:else}
    <svg
      class="size-[15px] fill-none stroke-current stroke-2 [stroke-linecap:round] [stroke-linejoin:round]"
      aria-hidden="true"
      viewBox="0 0 24 24"><path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5Z" /></svg
    >
  {/if}
</button>

<style>
  /* Tailwind's `max-*` variants are exclusive of the boundary, so the
     documented `(max-width: 899px)` narrow breakpoint stays hand-written —
     at exactly 899px it must keep agreeing with `NARROW_MAX_WIDTH` in
     `state/layout.svelte.ts`. */
  @media (max-width: 899px) {
    button {
      /* 44px is the smallest target a finger hits reliably. */
      min-width: 44px;
      min-height: 44px;
    }
  }
</style>
