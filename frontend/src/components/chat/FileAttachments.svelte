<script lang="ts">
  /**
   * Non-image files on a message: audio and video play inline, everything
   * else is a download card. Media elements cannot set Authorization headers,
   * so they ride the same tokened URL the image tiers use; the download card
   * instead fetches bytes with a header and saves them under the uploaded name.
   */
  import { downloadFile, fileLabel, humanSize } from "../../lib/files";
  import { authenticatedResourceUrl } from "../../lib/socket-auth";
  import type { FileRef } from "../../lib/contracts";

  interface Props {
    files: FileRef[];
  }

  let { files }: Props = $props();
  let downloading = $state<string | null>(null);
  let downloadError = $state("");

  async function save(file: FileRef): Promise<void> {
    if (downloading) return;
    downloading = file.id;
    downloadError = "";
    try {
      await downloadFile(file);
    } catch {
      downloadError = `could not download ${fileLabel(file, 0)}`;
    } finally {
      downloading = null;
    }
  }
</script>

<div class="mt-2 grid w-full max-w-[720px] gap-2">
  {#each files as file, index (file.id)}
    {#if file.kind === "audio"}
      <div class="grid gap-1 overflow-hidden rounded-md border border-line bg-ink-2 px-2.5 py-2">
        <audio
          class="h-9 w-full"
          controls
          preload="metadata"
          src={authenticatedResourceUrl(file.urls.original)}
        ></audio>
        <span class="truncate text-[10px] text-cream-faint"
          >{fileLabel(file, index)} · {file.mime} · {humanSize(file.bytes)}</span
        >
      </div>
    {:else if file.kind === "video"}
      <div class="grid gap-1 overflow-hidden rounded-md border border-line bg-ink-2 px-2.5 py-2">
        <!-- eslint-disable-next-line svelte/no-unused-svelte-ignore -- svelte-check warns, the eslint plugin does not -->
        <!-- svelte-ignore a11y_media_has_caption -- arbitrary uploads have no caption sidecar -->
        <video
          class="block max-h-80 w-full rounded bg-ink"
          controls
          preload="metadata"
          src={authenticatedResourceUrl(file.urls.original)}
        ></video>
        <span class="truncate text-[10px] text-cream-faint"
          >{fileLabel(file, index)} · {file.mime} · {humanSize(file.bytes)}</span
        >
      </div>
    {:else}
      <div
        class="card grid items-center gap-2.5 overflow-hidden rounded-md border border-line bg-ink-2 px-2.5 py-2 [grid-template-columns:24px_minmax(0,1fr)_auto_auto]"
      >
        <span class="text-center text-[15px]" aria-hidden="true">📎</span>
        <span class="truncate text-xs text-cream" title={fileLabel(file, index)}
          >{fileLabel(file, index)}</span
        >
        <span class="truncate text-[10px] text-cream-faint">{file.mime} · {humanSize(file.bytes)}</span>
        <button
          class="download min-h-11 border-0 bg-transparent p-0 text-[11px] text-copper-hot hover:bg-transparent hover:underline disabled:cursor-wait disabled:opacity-60"
          type="button"
          disabled={downloading === file.id}
          aria-label={`download ${fileLabel(file, index)}`}
          onclick={() => void save(file)}>{downloading === file.id ? "downloading…" : "download ↓"}</button
        >
      </div>
    {/if}
  {/each}
</div>
<div class="min-h-3.5 text-[10px] text-red" aria-live="polite">{downloadError}</div>
