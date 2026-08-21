<script lang="ts">
  import ImageViewer from "./ImageViewer.svelte";
  import { fileLabel } from "../../lib/files";
  import { authenticatedResourceUrl } from "../../lib/socket-auth";
  import { dialogs } from "../../state/dialogs.svelte.js";
  import type { FileRef } from "../../lib/contracts";

  interface Props {
    images: FileRef[];
  }

  let { images }: Props = $props();

  function view(index: number): void {
    dialogs.open(ImageViewer, { images, initialIndex: index });
  }
</script>

<div
  class="grid"
  class:single={images.length === 1}
  class:pair={images.length === 2}
  class:quad={images.length === 3 || images.length === 4}
  class:many={images.length >= 5}
>
  {#each images as image, index (image.id)}
    <button
      type="button"
      class="tile"
      aria-label={`view ${fileLabel(image, index)}`}
      onclick={() => {
        view(index);
      }}
    >
      <img
        src={authenticatedResourceUrl(image.urls.thumb)}
        alt={fileLabel(image, index)}
        width={image.thumb?.width ?? image.width}
        height={image.thumb?.height ?? image.height}
        loading="lazy"
        decoding="async"
      />
    </button>
  {/each}
</div>

<style>
  .grid {
    display: grid;
    gap: 6px;
    width: min(100%, 720px);
    margin-top: 8px;
  }
  .pair,
  .quad {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .many {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .tile {
    min-width: 0;
    padding: 0;
    overflow: hidden;
    border-color: var(--color-line);
    border-radius: 6px;
    background: var(--color-ink-2);
    cursor: zoom-in;
  }
  .tile:hover {
    border-color: var(--color-copper);
    background: var(--color-ink-2);
  }
  .tile:focus-visible {
    outline: 2px solid var(--color-copper-hot);
    outline-offset: 2px;
  }
  .tile img {
    display: block;
    width: 100%;
    height: 100%;
    min-height: 120px;
    max-height: 300px;
    object-fit: cover;
    transition: opacity 0.15s ease;
  }
  .tile:hover img {
    opacity: 0.88;
  }
  .single .tile img {
    height: auto;
    max-height: 460px;
    object-fit: contain;
  }
  .pair .tile,
  .quad .tile,
  .many .tile {
    aspect-ratio: 4 / 3;
  }
  @media (max-width: 520px) {
    .grid {
      gap: 4px;
    }
    .tile img {
      min-height: 86px;
    }
  }
</style>
