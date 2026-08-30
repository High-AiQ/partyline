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

<input
  class="absolute h-px w-px overflow-hidden whitespace-nowrap [clip:rect(0,0,0,0)]"
  bind:this={picker}
  type="file"
  multiple
  onchange={chooseFiles}
  tabindex="-1"
/>

{#if selectedFiles.length}
  <div class="previews mb-2 flex gap-[7px] overflow-x-auto pb-0.5" aria-label="files ready to attach">
    {#each selectedFiles as selected, index (selected.preview ?? selected.file.name + String(index))}
      <div
        class="preview grid flex-none grid-cols-[38px_minmax(70px,120px)_38px] items-center overflow-hidden rounded-[5px] border border-line bg-ink-2"
      >
        {#if selected.preview}
          <img class="size-[38px] object-cover" src={selected.preview} alt="" />
        {:else}
          <span class="file-icon grid size-[38px] place-items-center p-0 text-[15px]" aria-hidden="true"
            >📎</span
          >
        {/if}
        <span class="truncate px-[7px] text-[10px] text-cream-dim" title={selected.file.name}
          >{selected.file.name}</span
        >
        <button
          class="min-h-11 w-[38px] rounded-none border-0 border-l border-line bg-transparent p-0 hover:bg-transparent"
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
  <div class="metadata mb-2 grid grid-cols-[1fr_1.5fr] gap-2">
    <label class="flex flex-col gap-[3px] text-[10px] text-cream-dim">
      title <span class="text-cream-faint">(optional, shared by this batch)</span>
      <input bind:value={fileTitle} maxlength="200" placeholder="what is shared?" />
    </label>
    <label class="flex flex-col gap-[3px] text-[10px] text-cream-dim">
      description <span class="text-cream-faint">(optional)</span>
      <input bind:value={fileDescription} maxlength="2000" placeholder="context for people and agents" />
    </label>
  </div>
{/if}

<style>
  @media (max-width: 520px) {
    .metadata {
      grid-template-columns: 1fr;
    }
    .preview {
      grid-template-columns: 36px minmax(60px, 105px) 38px;
    }
  }
</style>
