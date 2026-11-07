<script lang="ts">
  /** The compact toggle that decides whether a send carries the shared screen's frames. */
  import { tooltip } from "../../lib/tooltip";

  let { pressed = $bindable(true) }: { pressed?: boolean } = $props();
  const label = $derived(
    pressed
      ? "Attach screen frames: on — each message includes the shared screen"
      : "Attach screen frames: off — click to include the shared screen",
  );
</script>

<button
  type="button"
  class="attach-frames grid size-11 flex-none place-items-center p-0 {pressed
    ? 'border-copper text-copper-hot'
    : ''}"
  aria-label="Attach screen frames"
  aria-pressed={pressed}
  use:tooltip={{ label }}
  onclick={() => {
    pressed = !pressed;
  }}
>
  <svg
    class="size-[18px] fill-none stroke-current stroke-[1.8] [stroke-linecap:round] [stroke-linejoin:round]"
    viewBox="0 0 24 24"
    aria-hidden="true"
  >
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <circle cx="9" cy="9" r="2" />
    <path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21" />
    {#if !pressed}<path d="M3 3l18 18" />{/if}
  </svg>
</button>
