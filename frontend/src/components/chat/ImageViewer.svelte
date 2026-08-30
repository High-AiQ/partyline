<script lang="ts">
  import Modal from "../Modal.svelte";
  import { downloadFile, fileLabel } from "../../lib/files";
  import { authenticatedResourceUrl } from "../../lib/socket-auth";
  import type { FileRef } from "../../lib/contracts";

  interface Props {
    images: FileRef[];
    initialIndex: number;
    close: () => void;
  }

  let { images, initialIndex, close }: Props = $props();
  let index = $derived(initialIndex);
  const image = $derived(images[index] ?? images[0]);
  let downloadError = $state("");
  let downloading = $state(false);

  function move(delta: number): void {
    index = (index + delta + images.length) % images.length;
  }

  function onKeydown(event: KeyboardEvent): void {
    // App owns Escape for the whole dialog stack. Handling it here as well can
    // pop two layers when listener order changes; this viewer owns arrows only.
    if (images.length > 1 && event.key === "ArrowLeft") {
      event.preventDefault();
      move(-1);
    } else if (images.length > 1 && event.key === "ArrowRight") {
      event.preventDefault();
      move(1);
    }
  }

  async function downloadOriginal(): Promise<void> {
    const selected = image;
    if (!selected || downloading) return;
    downloading = true;
    downloadError = "";
    try {
      await downloadFile(selected);
    } catch {
      downloadError = "could not download the original image";
    } finally {
      downloading = false;
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#if image}
  <Modal title={image.title ?? `image ${String(index + 1)} of ${String(images.length)}`} wide {close}>
    <div class="flex min-h-0 flex-col gap-2.5">
      <div
        class="stage relative grid min-h-[180px] place-items-center overflow-hidden rounded-md border border-line bg-ink"
      >
        <img
          class="block h-auto max-h-[62dvh] w-auto max-w-full object-contain"
          src={authenticatedResourceUrl(image.urls.slim ?? image.urls.original)}
          alt={fileLabel(image, index)}
          width={image.slim?.width ?? image.width}
          height={image.slim?.height ?? image.height}
          decoding="async"
        />
        {#if images.length > 1}
          <button
            class="nav previous absolute top-1/2 left-2.5 h-[52px] w-11 -translate-y-1/2 border-[rgb(233_226_212/0.32)] bg-[rgb(14_16_15/0.75)] p-0 font-sans text-[34px] leading-none text-cream hover:bg-[rgb(14_16_15/0.75)]"
            type="button"
            aria-label="previous image"
            onclick={() => {
              move(-1);
            }}
          >
            <span aria-hidden="true">‹</span>
          </button>
          <button
            class="nav next absolute top-1/2 right-2.5 h-[52px] w-11 -translate-y-1/2 border-[rgb(233_226_212/0.32)] bg-[rgb(14_16_15/0.75)] p-0 font-sans text-[34px] leading-none text-cream hover:bg-[rgb(14_16_15/0.75)]"
            type="button"
            aria-label="next image"
            onclick={() => {
              move(1);
            }}
          >
            <span aria-hidden="true">›</span>
          </button>
        {/if}
      </div>
      <div class="details flex items-start justify-between gap-4">
        <div>
          {#if image.title}<h3 class="text-[13px] font-semibold text-cream">{image.title}</h3>{/if}
          {#if image.description}<p class="mt-[3px] whitespace-pre-wrap text-cream-dim">
              {image.description}
            </p>{/if}
          <span class="text-[10px] text-cream-faint"
            >{image.width}×{image.height} · {(image.bytes / 1_000_000).toFixed(2)} MB</span
          >
        </div>
        <button
          class="download min-h-11 flex-none border-0 bg-transparent p-0 text-[11px] leading-[44px] text-copper-hot hover:bg-transparent hover:underline disabled:cursor-wait disabled:opacity-60"
          type="button"
          disabled={downloading}
          onclick={downloadOriginal}>{downloading ? "downloading…" : "download original ↓"}</button
        >
      </div>
      <div class="min-h-3.5 text-right text-[10px] text-red" aria-live="polite">{downloadError}</div>
      {#if images.length > 1}
        <div class="position text-center text-[10px] text-cream-faint" aria-live="polite">
          {index + 1} / {images.length}
        </div>
      {/if}
    </div>
  </Modal>
{/if}
