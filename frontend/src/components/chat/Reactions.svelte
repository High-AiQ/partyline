<script lang="ts">
  import { REACTION_PALETTE, type ReactionEmoji, type ReactionResponse } from "../../lib/reaction-contracts";

  interface Props {
    messageId: number;
    reactions: ReactionResponse[];
    onToggle: (emoji: ReactionEmoji) => Promise<void>;
    showControl?: boolean;
    showChips?: boolean;
  }

  let { messageId, reactions, onToggle, showControl = true, showChips = true }: Props = $props();
  let row = $state<HTMLDivElement | null>(null);
  let pickerOpen = $state(false);
  let busy = $state<ReactionEmoji | null>(null);
  const palette = REACTION_PALETTE;

  function closePicker(): void {
    pickerOpen = false;
  }

  function onWindowPointerDown(event: PointerEvent): void {
    const target = event.target;
    if (pickerOpen && (!(target instanceof Node) || !row?.contains(target))) closePicker();
  }

  function onWindowKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") closePicker();
  }

  async function toggle(emoji: ReactionEmoji): Promise<void> {
    if (busy) return;
    busy = emoji;
    try {
      await onToggle(emoji);
      closePicker();
    } finally {
      busy = null;
    }
  }

  function label(reaction: ReactionResponse): string {
    const count = reaction.reactors.length;
    return `Toggle ${reaction.emoji} reaction${count ? ` · ${String(count)} ${count === 1 ? "reactor" : "reactors"}` : ""}`;
  }
</script>

<svelte:window onpointerdown={onWindowPointerDown} onkeydown={onWindowKeydown} />

{#if showControl || (showChips && reactions.length > 0)}
  <div
    bind:this={row}
    class={showControl
      ? "reaction-widget relative inline-flex items-center"
      : "reaction-chips mt-1.5 flex flex-wrap items-center gap-1.5"}
    data-message-id={String(messageId)}
  >
    {#if showControl}
      <button
        class="reaction-add grid size-7 cursor-pointer place-items-center rounded border border-line bg-ink-2 p-0 text-cream-faint opacity-0 transition-opacity duration-150 pointer-events-none hover:bg-copper hover:text-ink group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto"
        type="button"
        aria-label="Add reaction"
        aria-expanded={pickerOpen}
        onclick={() => (pickerOpen = !pickerOpen)}
      >
        <svg
          class="size-[14px] fill-none stroke-current stroke-[1.7] [stroke-linecap:round] [stroke-linejoin:round]"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="8.5" />
          <circle cx="9" cy="10" r="0.8" fill="currentColor" stroke="none" />
          <circle cx="15" cy="10" r="0.8" fill="currentColor" stroke="none" />
          <path d="M8.5 14c1 1.5 2.2 2.2 3.5 2.2s2.5-.7 3.5-2.2" />
        </svg>
      </button>
      <div
        class="reaction-picker absolute right-0 top-full z-20 mt-1 flex items-center gap-0.5 rounded border border-panel-line bg-panel px-1 py-0.5 shadow-lg transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100"
        class:picker-open={pickerOpen}
        aria-label="Reaction picker"
      >
        {#each palette as emoji (emoji)}
          <button
            class="reaction-choice h-7 min-w-7 cursor-pointer border-transparent bg-transparent p-0 text-base leading-none hover:border-copper hover:bg-copper/15"
            type="button"
            aria-label={`React with ${emoji}`}
            disabled={busy !== null}
            onclick={() => void toggle(emoji)}
          >
            {emoji}
          </button>
        {/each}
      </div>
    {/if}
    {#if showChips && reactions.length > 0}
      {#each reactions as reaction (reaction.emoji)}
        <button
          class="reaction-chip inline-flex h-7 cursor-pointer items-center gap-1 rounded-full border border-panel-line bg-ink-3 px-2 text-[11px] text-cream-dim transition-colors duration-150 hover:border-copper hover:bg-copper/15 hover:text-cream"
          class:mine={reaction.mine}
          type="button"
          aria-label={label(reaction)}
          aria-pressed={reaction.mine}
          title={reaction.reactors.join(", ")}
          disabled={busy !== null}
          onclick={() => void toggle(reaction.emoji)}
        >
          <span aria-hidden="true">{reaction.emoji}</span>
          <span>{reaction.reactors.length}</span>
        </button>
      {/each}
    {/if}
  </div>
{/if}

<style>
  /* Touch screens have no hover to reveal the add control, so leave it muted
     but visible while preserving the stronger pointer hover treatment. */
  @media (hover: none) {
    .reaction-add {
      opacity: 0.65;
      pointer-events: auto;
    }
  }

  .reaction-picker {
    pointer-events: none;
    opacity: 0;
  }

  .reaction-picker.picker-open {
    pointer-events: auto;
    opacity: 1;
  }

  .reaction-chip.mine {
    border-color: var(--color-copper);
    background: rgb(217 142 74 / 0.16);
    color: var(--color-copper-hot);
  }
</style>
