<script lang="ts">
  import { REACTION_PALETTE, type ReactionEmoji, type ReactionResponse } from "../../lib/reaction-contracts";

  interface Props {
    messageId: number;
    reactions: ReactionResponse[];
    onToggle: (emoji: ReactionEmoji) => Promise<void>;
  }

  let { messageId, reactions, onToggle }: Props = $props();
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

<div
  bind:this={row}
  class="reaction-row group relative mt-2 flex min-h-7 flex-wrap items-center gap-1.5"
  data-message-id={String(messageId)}
>
  <button
    class="reaction-add h-7 w-7 cursor-pointer border-panel-line bg-panel p-0 text-sm text-cream-faint opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100 hover:border-copper hover:bg-copper/15 hover:text-copper-hot"
    type="button"
    aria-label="Add reaction"
    aria-expanded={pickerOpen}
    onclick={() => (pickerOpen = !pickerOpen)}
  >
    +
  </button>
  <div
    class="reaction-picker flex items-center gap-0.5 rounded border border-panel-line bg-panel px-1 py-0.5 shadow-lg transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100"
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
</div>

<style>
  /* Touch screens have no hover to reveal the add control, so give it a
     persistent, finger-sized target while preserving pointer hover behavior. */
  @media (hover: none) {
    .reaction-add {
      opacity: 1;
      pointer-events: auto;
      min-width: 44px;
      min-height: 44px;
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
