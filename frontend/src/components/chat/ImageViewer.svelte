<script lang="ts">
  import Modal from "../Modal.svelte";
  import { imageLabel } from "../../lib/images";
  import type { ImageRef } from "../../lib/contracts";

  interface Props {
    images: ImageRef[];
    initialIndex: number;
    close: () => void;
  }

  let { images, initialIndex, close }: Props = $props();
  let index = $derived(initialIndex);
  const image = $derived(images[index] ?? images[0]);

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
</script>

<svelte:window onkeydown={onKeydown} />

{#if image}
  <Modal title={image.title ?? `image ${String(index + 1)} of ${String(images.length)}`} wide {close}>
    <div class="viewer">
      <div class="stage">
        <img
          src={image.urls.original}
          alt={imageLabel(image, index)}
          width={image.width}
          height={image.height}
          decoding="async"
        />
        {#if images.length > 1}
          <button
            class="nav previous"
            type="button"
            aria-label="previous image"
            onclick={() => {
              move(-1);
            }}
          >
            <span aria-hidden="true">‹</span>
          </button>
          <button
            class="nav next"
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
      <div class="details">
        <div>
          {#if image.title}<h3>{image.title}</h3>{/if}
          {#if image.description}<p>{image.description}</p>{/if}
          <span class="dimensions"
            >{image.width}×{image.height} · {(image.bytes / 1_000_000).toFixed(2)} MB</span
          >
        </div>
        <a href={image.urls.original} target="_blank" rel="noreferrer">open original ↗</a>
      </div>
      {#if images.length > 1}
        <div class="position" aria-live="polite">{index + 1} / {images.length}</div>
      {/if}
    </div>
  </Modal>
{/if}

<style>
  .viewer {
    display: flex;
    min-height: 0;
    flex-direction: column;
    gap: 10px;
  }
  .stage {
    position: relative;
    display: grid;
    min-height: 180px;
    place-items: center;
    overflow: hidden;
    border: 1px solid var(--color-line);
    border-radius: 6px;
    background: var(--color-ink);
  }
  img {
    display: block;
    width: auto;
    max-width: 100%;
    height: auto;
    max-height: 62dvh;
    object-fit: contain;
  }
  .nav {
    position: absolute;
    top: 50%;
    width: 44px;
    height: 52px;
    padding: 0;
    transform: translateY(-50%);
    border-color: rgb(233 226 212 / 0.32);
    background: rgb(14 16 15 / 0.75);
    color: var(--color-cream);
    font-family: sans-serif;
    font-size: 34px;
    line-height: 1;
  }
  .previous {
    left: 10px;
  }
  .next {
    right: 10px;
  }
  .details {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
  }
  h3 {
    color: var(--color-cream);
    font-size: 13px;
    font-weight: 600;
  }
  p {
    margin-top: 3px;
    color: var(--color-cream-dim);
    white-space: pre-wrap;
  }
  .dimensions,
  .position {
    color: var(--color-cream-faint);
    font-size: 10px;
  }
  a {
    flex: none;
    min-height: 44px;
    color: var(--color-copper-hot);
    font-size: 11px;
    line-height: 44px;
    text-decoration: none;
  }
  a:hover {
    text-decoration: underline;
  }
  .position {
    text-align: center;
  }
</style>
