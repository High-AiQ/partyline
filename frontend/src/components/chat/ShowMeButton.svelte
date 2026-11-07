<script lang="ts">
  /** The idle "Show me" icon button; the walkthrough's recording bar lives in WalkthroughControl. */
  import { room } from "../../state/room.svelte.js";
  import { tooltip } from "../../lib/tooltip";
  import ComposerBubble from "./ComposerBubble.svelte";

  let { error, onbegin }: { error: string; onbegin: () => void } = $props();
  // A live ordinary share blocks a walkthrough, which needs a share of its own.
  const disabled = $derived(Boolean(room.screenShare && room.screenShare.status !== "declined"));
  const label = "Show me: record a narrated walkthrough";
</script>

<div class="flex flex-none" role="group" aria-label="Walkthrough">
  <button
    type="button"
    class="show-me grid size-11 flex-none place-items-center p-0 disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-line disabled:hover:bg-ink-3 disabled:hover:text-cream-dim"
    aria-label={label}
    use:tooltip={{ label }}
    {disabled}
    onclick={onbegin}
  >
    <svg
      class="size-[18px] fill-none stroke-current stroke-[1.8] [stroke-linecap:round] [stroke-linejoin:round]"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8M12 17v4" />
      <circle cx="12" cy="10" r="2.5" class="fill-current stroke-none" />
    </svg>
  </button>
  {#if error}
    <ComposerBubble><span role="alert" class="text-red">{error}</span></ComposerBubble>
  {/if}
</div>
