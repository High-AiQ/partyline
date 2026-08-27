<script lang="ts">
  /**
   * The actions panel for one line.
   *
   * `position: fixed` rather than absolute, because `#convs` scrolls and an
   * absolutely positioned child is clipped by it — the last row's menu worst of
   * all. Fixed coordinates then have to be re-derived whenever they stop
   * meaning anything, which is what `place()` and the window listeners are for.
   */
  import { tick } from "svelte";
  import type { Conversation } from "../../lib/contracts";

  interface Props {
    anchor: HTMLButtonElement;
    conversation: Conversation;
    close: () => void;
    onrename: (conversation: Conversation) => void;
    onclaims: (conversation: Conversation) => void;
    oncloseprocesses: (conversation: Conversation) => void;
    ondelete: (conversation: Conversation) => void;
  }

  let { anchor, conversation, close, onrename, onclaims, oncloseprocesses, ondelete }: Props = $props();

  let panel = $state<HTMLDivElement | null>(null);
  let top = $state(0);
  let left = $state(0);

  /** Flip above the anchor rather than hang off the bottom of the window, and
   *  never let the panel run past either edge. */
  function place(): void {
    if (!panel) return;
    const at = anchor.getBoundingClientRect();
    const box = panel.getBoundingClientRect();
    const below = at.bottom + 6;
    top = below + box.height > innerHeight - 8 ? Math.max(8, at.top - box.height - 6) : below;
    left = Math.min(Math.max(8, at.right - box.width), innerWidth - box.width - 8);
  }

  $effect(() => {
    // Measure once the panel is in the DOM, then take focus so the menu is
    // usable from the keyboard and Escape has somewhere to fire from.
    void tick().then(() => {
      place();
      panel?.querySelector("button")?.focus();
    });
  });

  /**
   * Read the conversation *before* closing.
   *
   * Props are lazy getters into the parent's scope, and `close()` is what sets
   * the parent's `menu` back to null — so reading `conversation` afterwards
   * evaluates `null.conversation` and throws. Capturing first is not a style
   * preference here; the other order is a crash.
   */
  function choose(run: (conversation: Conversation) => void): () => void {
    const chosen = conversation;
    return () => {
      close();
      run(chosen);
    };
  }
</script>

<!-- A menu pinned to viewport coordinates has to close when those coordinates
     stop meaning anything: a scrolled rail, a resized window, a key. -->
<svelte:window
  on:resize={close}
  on:scroll|capture={close}
  on:keydown={(e) => {
    if (e.key === "Escape") close();
  }}
/>

<div
  class="conv-menu fixed z-60 flex min-w-[132px] flex-col rounded-md border border-panel-line bg-panel p-[5px]"
  bind:this={panel}
  style:top="{top}px"
  style:left="{left}px"
  role="menu"
  aria-label="line actions for {conversation.name}"
>
  <button
    type="button"
    role="menuitem"
    class="rounded-[3px] border-0 bg-transparent p-2 px-[11px] text-left text-[10.5px] whitespace-nowrap tracking-[0.06em] text-cream-dim transition-colors duration-100 hover:bg-copper hover:text-ink focus-visible:bg-copper focus-visible:text-ink focus-visible:outline-0"
    onclick={choose(onrename)}>rename</button
  >
  <button
    type="button"
    role="menuitem"
    class="rounded-[3px] border-0 bg-transparent p-2 px-[11px] text-left text-[10.5px] whitespace-nowrap tracking-[0.06em] text-cream-dim transition-colors duration-100 hover:bg-copper hover:text-ink focus-visible:bg-copper focus-visible:text-ink focus-visible:outline-0"
    onclick={choose(onclaims)}>claims</button
  >
  <button
    type="button"
    role="menuitem"
    class="close-processes rounded-[3px] border-0 bg-transparent p-2 px-[11px] text-left text-[10.5px] whitespace-nowrap tracking-[0.06em] text-copper-hot transition-colors duration-100 hover:bg-copper hover:text-ink focus-visible:bg-copper focus-visible:text-ink focus-visible:outline-0"
    onclick={choose(oncloseprocesses)}>close processes</button
  >
  <button
    type="button"
    role="menuitem"
    class="delete rounded-[3px] border-0 bg-transparent p-2 px-[11px] text-left text-[10.5px] whitespace-nowrap tracking-[0.06em] text-red transition-colors duration-100 hover:bg-red hover:text-cream focus-visible:bg-red focus-visible:text-cream focus-visible:outline-0"
    onclick={choose(ondelete)}>delete</button
  >
</div>

<style>
  /* The multi-layer shadow, the `menu-in` entrance, and the copper hairline
       are a poor fit for utility classes: the hairline is a pseudo-element and
       the animation is not a theme token. */
  .conv-menu {
    box-shadow:
      0 18px 42px rgb(0 0 0 / 0.55),
      0 2px 6px rgb(0 0 0 / 0.4),
      inset 0 1px 0 rgb(233 226 212 / 0.04);
    animation: menu-in 0.12s ease-out;
  }
  /* copper hairline, echoing the active-line marker */
  .conv-menu::before {
    content: "";
    position: absolute;
    left: 9px;
    right: 9px;
    top: -1px;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--color-copper), transparent);
    opacity: 0.55;
  }
</style>
