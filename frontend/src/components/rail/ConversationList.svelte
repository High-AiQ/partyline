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
    ondelete: (conversation: Conversation) => void;
  }

  interface MenuState {
    anchor: HTMLButtonElement;
    conversation: Conversation;
  }

  let { onrename, ondelete }: Props = $props();

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

<nav id="convs" aria-label="lines">
  {#each room.conversations as conversation (conversation.id)}
    {@const open = menu?.conversation.id === conversation.id}
    <div class="conv-row" class:menu-open={open}>
      <button
        class="conv"
        class:active={room.conversation?.id === conversation.id}
        title={conversation.topic || undefined}
        onclick={() => room.open(conversation)}
      >
        {conversation.name}
      </button>
      <div class="conv-actions">
        <button
          class="conv-more"
          type="button"
          title="line actions"
          aria-label="line actions for {conversation.name}"
          aria-expanded={open}
          onclick={(event) => toggle(event, conversation)}>⋯</button
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
    {ondelete}
  />
{/if}

<style>
  #convs {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 10px 0;
  }

  .conv-row {
    position: relative;
    display: flex;
    align-items: stretch;
  }
  .conv {
    display: block;
    flex: 1;
    min-width: 0;
    width: 100%;
    text-align: left;
    background: none;
    border: 0;
    cursor: pointer;
    font: inherit;
    color: var(--color-cream-dim);
    padding: 9px 54px 9px 20px;
    position: relative;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .conv:hover,
  .conv-row:focus-within .conv,
  .conv-row.menu-open .conv {
    color: var(--color-cream);
    background: var(--color-ink-3);
  }

  .conv.active {
    color: var(--color-copper-hot);
    background: var(--color-ink-3);
  }
  .conv.active::before {
    content: "";
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--color-copper);
  }

  .conv-actions {
    position: absolute;
    right: 8px;
    top: 50%;
    transform: translateY(-50%);
    display: flex;
    align-items: center;
    gap: 4px;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.15s;
  }
  .conv-row:hover .conv-actions,
  .conv-row:focus-within .conv-actions,
  .conv-row.menu-open .conv-actions {
    opacity: 1;
    pointer-events: auto;
  }
  /* A touch screen has no hover to reveal them with. */
  @media (hover: none) {
    .conv-actions {
      opacity: 1;
      pointer-events: auto;
    }
  }

  .conv-more {
    width: 44px;
    height: 44px;
    padding: 0;
    background: var(--color-ink-2);
    color: var(--color-cream-faint);
    font-size: 16px;
    line-height: 1;
  }
  .conv-more:hover,
  .conv-more[aria-expanded="true"] {
    color: var(--color-ink);
    background: var(--color-copper);
  }
</style>
