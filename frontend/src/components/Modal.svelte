<script lang="ts">
  /**
   * The one modal chrome. Every dialog in the app is this plus a body, which is
   * why the delete-line, delete-forever and stop-the-server dialogs look and
   * behave alike without three people keeping them in step.
   */
  import type { Snippet } from "svelte";
  import { tooltip } from "../lib/tooltip";

  interface Props {
    title: string;
    wide?: boolean;
    /** A fixed-size workspace (full screen on a phone) whose body lays itself out and scrolls itself. */
    panel?: boolean;
    close: () => void;
    children: Snippet;
    /** Controls in the header between the title and the close button (settings search). */
    tools?: Snippet;
  }

  let { title, wide = false, panel = false, close, children, tools }: Props = $props();

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
    class="modal flex {panel
      ? 'h-[min(860px,90dvh)] w-[min(1080px,96vw)] max-[899px]:h-dvh max-[899px]:w-full max-[899px]:rounded-none max-[899px]:border-0'
      : wide
        ? 'max-h-[82dvh] w-[min(980px,96vw)]'
        : 'max-h-[82dvh] w-[min(560px,92vw)]'} flex-col rounded-lg border border-line bg-ink-2 shadow-[0_24px_60px_rgb(0_0_0/0.55)]"
    role="dialog"
    aria-modal="true"
    aria-label={title}
  >
    <header
      class="flex min-h-[52px] flex-none {tools
        ? 'flex-wrap gap-x-4'
        : ''} items-center justify-between border-b border-dashed border-line py-1 pr-2 pl-5"
    >
      <h2 class="font-serif text-[20px] font-normal text-cream italic">{title}</h2>
      {#if tools}{@render tools()}{/if}
      <button
        class="close size-11 cursor-pointer border-0 bg-transparent p-0 text-[14px] text-cream-faint hover:bg-red hover:text-ink"
        type="button"
        use:tooltip={{ label: "close" }}
        aria-label="close"
        onclick={close}>✕</button
      >
    </header>
    <div
      class="content flex min-h-0 flex-col {panel
        ? 'flex-1 overflow-hidden'
        : 'gap-[10px] overflow-y-auto px-5 pt-[14px] pb-5'}"
    >
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
</style>
