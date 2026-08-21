<script lang="ts">
  import { onDestroy } from "svelte";
  import { MAX_FILES_PER_MESSAGE } from "../../lib/files";
  import type { FileIntake, PendingFiles } from "../../lib/files";

  interface Props {
    openPicker: number;
    intake: FileIntake;
    onselection: (selection: PendingFiles) => void;
    onlimit: () => void;
  }

  interface SelectedFile {
    file: File;
    preview: string | null;
  }

  let { openPicker, intake, onselection, onlimit }: Props = $props();
  let picker = $state<HTMLInputElement | null>(null);
  const selectedFiles = $state<SelectedFile[]>([]);
  let fileTitle = $state("");
  let fileDescription = $state("");
  let openedAt = 0;
  let intakeGeneration = 0;

  $effect(() => {
    if (openPicker !== openedAt) {
      openedAt = openPicker;
      picker?.click();
    }
  });

  $effect(() => {
    if (intake.generation === intakeGeneration) return;
    intakeGeneration = intake.generation;
    addFiles(intake.files);
  });

  $effect(() => {
    onselection({
      files: selectedFiles.map(({ file }) => file),
      title: fileTitle,
      description: fileDescription,
    });
  });

  onDestroy(() => {
    for (const selected of selectedFiles) {
      if (selected.preview) URL.revokeObjectURL(selected.preview);
    }
  });

  function chooseFiles(event: Event): void {
    const input = event.currentTarget;
    if (!(input instanceof HTMLInputElement) || !input.files?.length) return;
    const files = Array.from(input.files);
    input.value = "";
    addFiles(files);
  }

  function addFiles(files: File[]): void {
    if (selectedFiles.length + files.length > MAX_FILES_PER_MESSAGE) {
      onlimit();
      return;
    }
    selectedFiles.push(
      ...files.map((file) => ({
        file,
        preview: file.type.startsWith("image/") ? URL.createObjectURL(file) : null,
      })),
    );
  }

  function removeFile(index: number): void {
    const removed = selectedFiles[index];
    if (removed?.preview) URL.revokeObjectURL(removed.preview);
    selectedFiles.splice(index, 1);
  }
</script>

<input class="file-input" bind:this={picker} type="file" multiple onchange={chooseFiles} tabindex="-1" />

{#if selectedFiles.length}
  <div class="previews" aria-label="files ready to attach">
    {#each selectedFiles as selected, index (selected.preview ?? selected.file.name + String(index))}
      <div class="preview">
        {#if selected.preview}
          <img src={selected.preview} alt="" />
        {:else}
          <span class="file-icon" aria-hidden="true">📎</span>
        {/if}
        <span title={selected.file.name}>{selected.file.name}</span>
        <button
          type="button"
          aria-label={`remove ${selected.file.name}`}
          onclick={() => {
            removeFile(index);
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
      <input bind:value={fileTitle} maxlength="200" placeholder="what is shared?" />
    </label>
    <label>
      description <span>(optional)</span>
      <input bind:value={fileDescription} maxlength="2000" placeholder="context for people and agents" />
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
  .preview .file-icon {
    display: grid;
    width: 38px;
    height: 38px;
    place-items: center;
    padding: 0;
    font-size: 15px;
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
