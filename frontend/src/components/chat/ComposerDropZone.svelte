<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    children: Snippet;
    disabled: boolean;
    onfiles: (files: File[]) => void;
    oninvalid: () => void;
  }

  let { children, disabled, onfiles, oninvalid }: Props = $props();
  let dragDepth = $state(0);
  const dragging = $derived(dragDepth > 0);

  function hasFiles(event: DragEvent): boolean {
    return Array.from(event.dataTransfer?.types ?? []).includes("Files");
  }

  function queue(files: File[]): void {
    const images = files.filter((file) => file.type.startsWith("image/"));
    if (images.length !== files.length) oninvalid();
    if (images.length) onfiles(images);
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
    queue(Array.from(event.dataTransfer?.files ?? []));
  }

  function onPaste(event: ClipboardEvent): void {
    if (disabled) return;
    const files = Array.from(event.clipboardData?.items ?? [])
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
    if (!files.length) return;
    event.preventDefault();
    queue(files);
  }
</script>

<div
  id="composer"
  role="group"
  aria-label="message composer"
  class:dragging
  ondragenter={onDragEnter}
  ondragover={onDragOver}
  ondragleave={onDragLeave}
  ondrop={onDrop}
  onpaste={onPaste}
>
  {@render children()}
  {#if dragging}
    <div class="drop-hint" aria-hidden="true">
      <svg viewBox="0 0 24 24">
        <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v5h14v-5" />
      </svg>
      <span>drop images here</span>
    </div>
  {/if}
</div>

<style>
  #composer {
    position: relative;
    padding: 14px 28px 20px;
    border-top: 1px solid var(--color-line);
  }
  #composer.dragging {
    background: rgb(217 142 74 / 0.08);
  }
  .drop-hint {
    position: absolute;
    z-index: 4;
    inset: 7px 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 9px;
    border: 2px dashed var(--color-copper-hot);
    border-radius: 8px;
    background: rgb(14 16 15 / 0.94);
    color: var(--color-cream);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    pointer-events: none;
  }
  .drop-hint svg {
    width: 22px;
    fill: none;
    stroke: var(--color-copper-hot);
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-width: 1.8;
  }
  @media (max-width: 899px) {
    #composer {
      padding: 10px 12px 14px;
    }
    .drop-hint {
      inset: 5px 7px;
    }
  }
</style>
