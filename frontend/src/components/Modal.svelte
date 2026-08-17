<script lang="ts">
  /**
   * The one modal chrome. Every dialog in the app is this plus a body, which is
   * why the delete-line, delete-forever and stop-the-server dialogs look and
   * behave alike without three people keeping them in step.
   */
  import type { Snippet } from "svelte";

  interface Props {
    title: string;
    wide?: boolean;
    close: () => void;
    children: Snippet;
  }

  let { title, wide = false, close, children }: Props = $props();

  /** A click that starts inside the panel and ends on the backdrop is a drag,
   *  not a dismissal — losing a half-typed confirmation to a sloppy text
   *  selection is a bad way to find that out. */
  let pressedBackdrop = $state(false);
</script>

<div
  class="overlay"
  role="presentation"
  onmousedown={(event) => (pressedBackdrop = event.target === event.currentTarget)}
  onclick={(event) => {
    if (event.target === event.currentTarget && pressedBackdrop) close();
  }}
>
  <div class="modal" class:wide role="dialog" aria-modal="true" aria-label={title}>
    <header>
      <h2>{title}</h2>
      <button class="close" type="button" title="close" aria-label="close" onclick={close}>✕</button>
    </header>
    <div class="content">
      {@render children()}
    </div>
  </div>
</div>

<style>
  .overlay {
    position: fixed;
    inset: 0;
    background: rgb(8 10 9 / 0.75);
    backdrop-filter: blur(2px);
    z-index: 50;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .modal {
    background: var(--color-ink-2);
    border: 1px solid var(--color-line);
    border-radius: 8px;
    width: min(560px, 92vw);
    /* `dvh`: a soft keyboard shortens the viewport rather than covering it, and
       `vh` keeps measuring the taller pre-keyboard one — which crops exactly
       the dialogs that ask you to type something, the debrief and the
       type-the-name confirmations among them. */
    max-height: 82dvh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 24px 60px rgb(0 0 0 / 0.55);
    animation: arrive 0.22s ease both;
  }
  .modal.wide {
    width: min(980px, 96vw);
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex: none;
    min-height: 52px;
    padding: 4px 8px 4px 20px;
    border-bottom: 1px dashed var(--color-line);
  }
  h2 {
    font-family: var(--font-serif);
    font-style: italic;
    font-weight: 400;
    font-size: 20px;
    color: var(--color-cream);
  }
  .close {
    width: 44px;
    height: 44px;
    background: none;
    border: 0;
    color: var(--color-cream-faint);
    cursor: pointer;
    font-size: 14px;
    padding: 0;
  }
  .close:hover {
    color: var(--color-red);
    background: none;
  }

  .content {
    min-height: 0;
    padding: 14px 20px 20px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
</style>
