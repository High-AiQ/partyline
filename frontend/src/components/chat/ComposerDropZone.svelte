<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    children: Snippet;
    disabled: boolean;
    onfiles: (files: File[]) => void;
  }

  let { children, disabled, onfiles }: Props = $props();
  let dragDepth = $state(0);
  const dragging = $derived(dragDepth > 0);

  function hasFiles(event: DragEvent): boolean {
    return Array.from(event.dataTransfer?.types ?? []).includes("Files");
  }

  function onDragEnter(event: DragEvent): void {
    if (disabled || !hasFiles(event)) return;
    event.preventDefault();
    dragDepth++;
  }

  function onDragOver(event: DragEvent): void {
    if (disabled || !hasFiles(event)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  }

  function onDragLeave(event: DragEvent): void {
    if (!hasFiles(event)) return;
    dragDepth = Math.max(0, dragDepth - 1);
  }

  function onDrop(event: DragEvent): void {
    if (disabled || !hasFiles(event)) return;
    event.preventDefault();
    dragDepth = 0;
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length) onfiles(files);
  }

  function onPaste(event: ClipboardEvent): void {
    if (disabled) return;
    const files = Array.from(event.clipboardData?.items ?? [])
      .filter((item) => item.kind === "file")
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
    if (!files.length) return;
    event.preventDefault();
    onfiles(files);
  }
</script>

<div
  id="composer"
  role="group"
  aria-label="message composer"
  class="composer relative border-t border-line px-7 pt-3.5 pb-5 {dragging
    ? 'bg-[rgb(217_142_74/0.08)]'
    : ''}"
  ondragenter={onDragEnter}
  ondragover={onDragOver}
  ondragleave={onDragLeave}
  ondrop={onDrop}
  onpaste={onPaste}
>
  {@render children()}
  {#if dragging}
    <div
      class="drop-hint pointer-events-none absolute inset-x-5 inset-y-[7px] z-[4] flex items-center justify-center gap-[9px] rounded-lg border-2 border-dashed border-copper-hot bg-[rgb(14_16_15/0.94)] text-xs font-semibold tracking-[0.04em] text-cream"
      aria-hidden="true"
    >
      <svg
        class="size-[22px] fill-none stroke-copper-hot stroke-[1.8] [stroke-linecap:round] [stroke-linejoin:round]"
        viewBox="0 0 24 24"
      >
        <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v5h14v-5" />
      </svg>
      <span>drop files here</span>
    </div>
  {/if}
</div>

<style>
  /* Tailwind's `max-*` variants are exclusive of the boundary, so the
     documented `(max-width: 899px)` narrow breakpoint stays hand-written. */
  @media (max-width: 899px) {
    .composer {
      padding: 10px 12px 14px;
    }
    .drop-hint {
      inset: 5px 7px;
    }
  }
</style>
