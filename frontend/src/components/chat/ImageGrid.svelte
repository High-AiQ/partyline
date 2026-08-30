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

  const count = $derived(images.length);
  const gridCols = $derived(count >= 5 ? "grid-cols-3" : count >= 2 ? "grid-cols-2" : "");
  const multiImage = $derived(count >= 2);
  const singleImage = $derived(count === 1);
  const tileClass = $derived(multiImage ? "aspect-[4/3]" : "");
  const imgClass = $derived(
    singleImage ? "h-auto max-h-[460px] object-contain" : "h-full min-h-[120px] max-h-[300px] object-cover",
  );

  function view(index: number): void {
    dialogs.open(ImageViewer, { images, initialIndex: index });
  }
</script>

<div class="grid mt-2 w-full max-w-[720px] gap-1.5 {gridCols}">
  {#each images as image, index (image.id)}
    <button
      type="button"
      class="tile min-w-0 cursor-zoom-in overflow-hidden rounded-md border border-line bg-ink-2 p-0 hover:border-copper hover:bg-ink-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-copper-hot {tileClass}"
      aria-label={`view ${fileLabel(image, index)}`}
      onclick={() => {
        view(index);
      }}
    >
      <img
        class="tile-img block w-full transition-opacity duration-150 ease-in-out hover:opacity-[0.88] {imgClass}"
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
  @media (max-width: 520px) {
    .grid {
      gap: 4px;
    }
    .tile-img {
      min-height: 86px;
    }
  }
</style>
