<script lang="ts">
  import { onDestroy } from "svelte";
  import { MAX_IMAGES_PER_MESSAGE } from "../../lib/images";
  import type { PendingImages } from "../../lib/images";

  interface Props {
    openPicker: number;
    onselection: (selection: PendingImages) => void;
    onlimit: () => void;
  }

  interface SelectedImage {
    file: File;
    preview: string;
  }

  let { openPicker, onselection, onlimit }: Props = $props();
  let picker = $state<HTMLInputElement | null>(null);
  const selectedImages = $state<SelectedImage[]>([]);
  let imageTitle = $state("");
  let imageDescription = $state("");
  let openedAt = 0;

  $effect(() => {
    if (openPicker !== openedAt) {
      openedAt = openPicker;
      picker?.click();
    }
  });

  $effect(() => {
    onselection({
      files: selectedImages.map(({ file }) => file),
      title: imageTitle,
      description: imageDescription,
    });
  });

  onDestroy(() => {
    for (const selectedImage of selectedImages) URL.revokeObjectURL(selectedImage.preview);
  });

  function chooseImages(event: Event): void {
    const input = event.currentTarget;
    if (!(input instanceof HTMLInputElement) || !input.files?.length) return;
    const files = Array.from(input.files);
    input.value = "";
    if (selectedImages.length + files.length > MAX_IMAGES_PER_MESSAGE) {
      onlimit();
      return;
    }
    selectedImages.push(...files.map((file) => ({ file, preview: URL.createObjectURL(file) })));
  }

  function removeImage(index: number): void {
    const removed = selectedImages[index];
    if (removed) URL.revokeObjectURL(removed.preview);
    selectedImages.splice(index, 1);
  }
</script>

<input
  class="file-input"
  bind:this={picker}
  type="file"
  accept="image/*"
  multiple
  onchange={chooseImages}
  tabindex="-1"
/>

{#if selectedImages.length}
  <div class="previews" aria-label="images ready to attach">
    {#each selectedImages as selectedImage, index (selectedImage.preview)}
      <div class="preview">
        <img src={selectedImage.preview} alt="" />
        <span title={selectedImage.file.name}>{selectedImage.file.name}</span>
        <button
          type="button"
          aria-label={`remove ${selectedImage.file.name}`}
          onclick={() => {
            removeImage(index);
          }}
        >
          ×
        </button>
      </div>
    {/each}
  </div>
  <div class="metadata">
    <label>
      title <span>(optional, shared by this batch)</span>
      <input bind:value={imageTitle} maxlength="200" placeholder="what is shown?" />
    </label>
    <label>
      description <span>(optional)</span>
      <input bind:value={imageDescription} maxlength="2000" placeholder="context for people and agents" />
    </label>
  </div>
{/if}

<style>
  .file-input {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
  }
  .previews {
    display: flex;
    gap: 7px;
    overflow-x: auto;
    margin-bottom: 8px;
    padding-bottom: 2px;
  }
  .preview {
    display: grid;
    grid-template-columns: 38px minmax(70px, 120px) 38px;
    align-items: center;
    flex: none;
    overflow: hidden;
    border: 1px solid var(--color-line);
    border-radius: 5px;
    background: var(--color-ink-2);
  }
  .preview img {
    width: 38px;
    height: 38px;
    object-fit: cover;
  }
  .preview span {
    overflow: hidden;
    padding: 0 7px;
    color: var(--color-cream-dim);
    font-size: 10px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .preview button {
    width: 38px;
    min-height: 44px;
    padding: 0;
    border: 0;
    border-left: 1px solid var(--color-line);
    border-radius: 0;
    background: transparent;
  }
  .metadata {
    display: grid;
    grid-template-columns: 1fr 1.5fr;
    gap: 8px;
    margin-bottom: 8px;
  }
  .metadata label {
    display: flex;
    flex-direction: column;
    gap: 3px;
    color: var(--color-cream-dim);
    font-size: 10px;
  }
  .metadata label span {
    color: var(--color-cream-faint);
  }
  .metadata input {
    min-width: 0;
  }
  @media (max-width: 520px) {
    .metadata {
      grid-template-columns: 1fr;
    }
    .preview {
      grid-template-columns: 36px minmax(60px, 105px) 38px;
    }
  }
</style>
