<script lang="ts">
  import { room } from "../../state/room.svelte.js";
  import { screenStatus } from "../../state/screen-status.svelte.js";
  import { tooltip } from "../../lib/tooltip";
  import { PopupMenu } from "../../lib/popup-menu.svelte";
  import ComposerBubble from "./ComposerBubble.svelte";

  let { error, online, onbegin }: { error: string; online: boolean; onbegin: () => void } = $props();
  const popup = new PopupMenu();
  const blocked = $derived(Boolean(room.screenShare && room.screenShare.status !== "declined"));
  const reason = $derived(
    blocked
      ? "Stop the live share before recording a walkthrough"
      : !online
        ? "Connect a computer to record a walkthrough"
        : "",
  );
  const label = "Screen: share screen + record voice (Show me), or share screen only";
</script>

<svelte:window onkeydown={popup.keydown} onpointerdown={popup.pointerdown} />
<div class="flex flex-none" bind:this={popup.container}>
  <button
    bind:this={popup.anchor}
    type="button"
    class="screen-menu grid size-11 flex-none place-items-center p-0"
    aria-label={label}
    aria-haspopup="menu"
    aria-expanded={popup.open}
    use:tooltip={{ label }}
    onclick={popup.toggle}
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
  {#if popup.open}
    <div
      bind:this={popup.menu}
      role="menu"
      aria-label="Screen"
      class="absolute bottom-full left-7 z-60 mb-1 flex w-72 max-w-[calc(100%-3.5rem)] flex-col rounded-md border border-panel-line bg-panel p-1"
    >
      <button
        type="button"
        role="menuitem"
        aria-disabled={Boolean(reason)}
        use:tooltip={{ label: reason }}
        class="border-0 bg-transparent p-2 text-left aria-disabled:opacity-45 {reason
          ? ''
          : 'hover:bg-copper hover:text-ink'} focus-visible:bg-copper focus-visible:text-ink"
        onclick={() => {
          if (!reason) {
            popup.close();
            onbegin();
          }
        }}
      >
        <span class="block">Share screen + record voice</span>
        <span class="block text-xs">Frames + transcript on stop</span>
      </button>
      <button
        type="button"
        role="menuitem"
        class="border-0 bg-transparent p-2 text-left hover:bg-copper hover:text-ink focus-visible:bg-copper focus-visible:text-ink"
        onclick={() => {
          popup.close();
          screenStatus.openPicker++;
        }}
      >
        <span class="block">Share screen only</span>
        <span class="block text-xs">Live view · no voice</span>
      </button>
    </div>
  {/if}
  {#if error}<ComposerBubble><span role="alert" class="text-red">{error}</span></ComposerBubble>{/if}
</div>
