<script lang="ts">
  /**
   * The faint row under the composer: keyboard advice on the left, a draft
   * length counter on the right once the draft is long enough to matter.
   */
  import { COUNTER_FROM, COUNTER_WARN_FROM, MAX_MESSAGE_BODY } from "../../lib/composer";

  let { attached, length }: { attached: boolean; length: number } = $props();
  const counting = $derived(length >= COUNTER_FROM);
  const label = $derived(`${length.toLocaleString("en-US")} / ${MAX_MESSAGE_BODY.toLocaleString("en-US")}`);
</script>

<div class="hint mt-1.5 flex gap-3 text-[10px] text-cream-faint" class:blocked={!attached} class:counting>
  <span class="tip min-w-0 flex-1" aria-live="polite">
    {#if !attached}
      attach a process to message this line
    {:else}
      enter to send · shift+enter or ctrl+j for a new line · agents only wake when @mentioned · @all rings
      every running agent
    {/if}
  </span>
  <!-- Always in the row, empty until the draft is long: its reserved width keeps the
       hint's wrapping, and so the composer's height, the same at every length. -->
  <span
    class="count ml-auto min-w-[16ch] shrink-0 text-right tabular-nums"
    class:text-gold={length >= COUNTER_WARN_FROM && length < MAX_MESSAGE_BODY}
    class:text-red={length >= MAX_MESSAGE_BODY}>{counting ? label : ""}</span
  >
</div>

<style>
  /* Tailwind's `max-*` variants are exclusive of the boundary, so the
     documented `(max-width: 899px)` narrow breakpoint stays hand-written. */
  @media (max-width: 899px) {
    /* Three lines of keyboard advice, none of which applies to a touch
       keyboard, on the screen with the least room to spare. The counter
       alone remains, tucked into the composer's bottom padding so a long
       draft costs the page no height and moves nothing. */
    .hint:not(.blocked) {
      position: relative;
      height: 0;
      margin-top: 0;
    }
    .hint:not(.blocked) .tip {
      display: none;
    }
    .hint:not(.blocked) .count {
      position: absolute;
      right: 0.75rem;
      bottom: 2px;
      line-height: 1;
    }
  }
</style>
