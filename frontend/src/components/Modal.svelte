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
  class="overlay fixed inset-0 z-50 flex items-center justify-center bg-[rgb(8_10_9/0.75)] backdrop-blur-[2px]"
  role="presentation"
  onmousedown={(event) => (pressedBackdrop = event.target === event.currentTarget)}
  onclick={(event) => {
    if (event.target === event.currentTarget && pressedBackdrop) close();
  }}
>
  <!-- `max-h-[82dvh]`, not `vh` or `%`: a soft keyboard shortens the viewport
         rather than covering it, and `vh` keeps measuring the taller pre-keyboard
         one — which crops exactly the dialogs that ask you to type something. -->
  <div
    class="modal flex max-h-[82dvh] w-[min(560px,92vw)] flex-col rounded-lg border border-line bg-ink-2 shadow-[0_24px_60px_rgb(0_0_0/0.55)]"
    class:wide
    role="dialog"
    aria-modal="true"
    aria-label={title}
  >
    <header
      class="flex min-h-[52px] flex-none items-center justify-between border-b border-dashed border-line py-1 pr-2 pl-5"
    >
      <h2 class="font-serif text-[20px] font-normal text-cream italic">{title}</h2>
      <button
        class="close size-11 cursor-pointer border-0 bg-transparent p-0 text-[14px] text-cream-faint hover:bg-transparent hover:text-red"
        type="button"
        title="close"
        aria-label="close"
        onclick={close}>✕</button
      >
    </header>
    <div class="content flex min-h-0 flex-col gap-[10px] overflow-y-auto px-5 pt-[14px] pb-5">
      {@render children()}
    </div>
  </div>
</div>

<style>
  /* `arrive` is a theme token at 0.28s; the modal uses the same keyframes a
       shade faster, so the animation stays hand-written. */
  .modal {
    animation: arrive 0.22s ease both;
  }
  .modal.wide {
    width: min(980px, 96vw);
  }
</style>
