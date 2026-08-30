<script lang="ts">
  /**
   * The lines you can be on.
   *
   * The row's actions are hidden until hover, and the menu is a single instance
   * anchored to whichever ⋯ opened it. While a menu is open its row keeps its
   * actions lit, so the ⋯ does not vanish out from under the pointer on the way
   * down to the menu.
   */
  import LineMenu from "./LineMenu.svelte";
  import type { Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte";

  interface Props {
    onrename: (conversation: Conversation) => void;
    onclaims: (conversation: Conversation) => void;
    oncloseprocesses: (conversation: Conversation) => void;
    ondelete: (conversation: Conversation) => void;
  }

  interface MenuState {
    anchor: HTMLButtonElement;
    conversation: Conversation;
  }

  let { onrename, onclaims, oncloseprocesses, ondelete }: Props = $props();

  /** `{anchor, conversation}` while a menu is open, else null. */
  let menu = $state<MenuState | null>(null);

  function toggle(event: MouseEvent, conversation: Conversation): void {
    event.stopPropagation();
    if (!(event.currentTarget instanceof HTMLButtonElement)) return;
    const anchor = event.currentTarget;
    menu = menu?.anchor === anchor ? null : { anchor, conversation };
  }
</script>

<!-- Any click that is not on a ⋯ dismisses the menu. The buttons stop their own
     propagation, so this cannot fight with the toggle above. -->
<svelte:body on:click={() => (menu = null)} />

<nav id="convs" class="min-h-0 flex-1 overflow-y-auto py-2.5" aria-label="lines">
  {#each room.conversations as conversation (conversation.id)}
    {@const open = menu?.conversation.id === conversation.id}
    <div class="conv-row group relative flex items-stretch" class:menu-open={open}>
      <button
        class="conv relative flex min-w-0 w-full flex-1 cursor-pointer items-center gap-2 border-0 p-[9px] pl-5 pr-[54px] text-left text-[13.5px] [font-family:inherit] {room
          .conversation?.id === conversation.id
          ? 'bg-ink-3 text-copper-hot'
          : 'bg-transparent text-cream-dim group-hover:bg-ink-3 group-hover:text-cream group-focus-within:bg-ink-3 group-focus-within:text-cream group-[.menu-open]:bg-ink-3 group-[.menu-open]:text-cream'}"
        class:active={room.conversation?.id === conversation.id}
        title={conversation.topic || undefined}
        onclick={() => room.open(conversation)}
      >
        <span class="conv-name min-w-0 truncate">{conversation.name}</span>
        {#if conversation.live_count > 0}
          <span
            class="line-live inline-flex flex-none"
            title="{conversation.live_count} live"
            aria-label="{conversation.live_count} live"
            ><span class="led running" aria-hidden="true"></span></span
          >
        {/if}
      </button>
      <div
        class="conv-actions absolute top-1/2 right-2 flex -translate-y-1/2 items-center gap-1 opacity-0 transition-opacity pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto group-[.menu-open]:opacity-100 group-[.menu-open]:pointer-events-auto"
      >
        <button
          class="conv-more size-11 bg-ink-2 p-0 text-[16px] leading-none text-cream-faint hover:bg-copper hover:text-ink aria-expanded:bg-copper aria-expanded:text-ink"
          type="button"
          title="line actions"
          aria-label="line actions for {conversation.name}"
          aria-expanded={open}
          onclick={(event) => {
            toggle(event, conversation);
          }}>⋯</button
        >
      </div>
    </div>
  {/each}
</nav>

{#if menu}
  <LineMenu
    anchor={menu.anchor}
    conversation={menu.conversation}
    close={() => (menu = null)}
    {onrename}
    {onclaims}
    {oncloseprocesses}
    {ondelete}
  />
{/if}

<style>
  /* The active-line copper marker is a pseudo-element on a state class. */
  .conv.active::before {
    content: "";
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--color-copper);
  }

  /* A touch screen has no hover to reveal the row actions with, and Tailwind
     has no `(hover: none)` media-query variant. */
  @media (hover: none) {
    .conv-actions {
      opacity: 1;
      pointer-events: auto;
    }
  }
</style>
